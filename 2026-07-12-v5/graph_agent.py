"""
v5 Agent 执行层：基于 LangGraph 的 StateGraph 编排。

相比 v4 的手写「LLM 主导 + 工具调用闭环」循环，v5 用 LangGraph 的声明式图来编排：

    START ──▶ agent ──(有 tool_calls)──▶ tools ──▶ agent ──▶ ...
                     └──(无 tool_calls)──▶ memory ──▶ END

- agent 节点：ChatGoogleGenerativeAI（Gemini/Gemma）+ bind_tools，产出 AIMessage（可能含 tool_calls）
- tools 节点：LangGraph 预置 ToolNode 执行工具调用，产出 ToolMessage
- memory 节点：对话结束后抽取长期记忆并持久化（复用 v4 的 memory_store）
- 条件边：自定义 _should_continue 决定「继续调工具」还是「进入记忆节点收尾」

短期记忆用 LangGraph 的 MemorySaver checkpointer 管理（thread_id = session_id），
不再手动拼装 history；长期记忆复用 v4 的 memory_store（SQLite 持久化）。

工具层、LLM REST 接入层、会话存储均直接复用 v4 的 tools.py / llm_client.py / session_store.py。
"""
import os
import re
import json
import datetime

# langchain / langgraph 为可选依赖：仅在配置了 GEMINI_API_KEY（走 LLM 路径）时才需要。
# 无 key 时走关键词降级（_fallback_run），即使未安装这些包也能导入本模块。
try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.prebuilt import ToolNode
    from langgraph.checkpoint.memory import MemorySaver
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage
    from langchain_core.tools import tool
    from typing import Annotated, TypedDict
    from langgraph.graph.message import add_messages
    _HAVE_LANGGRAPH = True
except Exception:  # pragma: no cover - 依赖缺失时仅影响 LLM 路径
    _HAVE_LANGGRAPH = False

import llm_client
import tools as tools_mod
import memory_store as mem

# ---------------------------------------------------------------------------
# 1. 把 v4 的工具函数包装成 LangChain @tool（供 ToolNode 调用）
# ---------------------------------------------------------------------------
@tool
def get_profile(code: str) -> dict:
    """获取目标股票的上市板块、所属行业、主营业务、成立与上市日期等公司资料。当用户问及上市板块、主营业务、行业、公司资料时调用。"""
    return tools_mod.get_profile(code)


@tool
def get_history(code: str, start_date: str, end_date: str) -> dict:
    """获取目标股票历史日 K 线行情（开盘/收盘/最高/最低/成交量）。当用户问及历史价格、K线、某段时间行情时调用。"""
    return tools_mod.get_history(code, start_date, end_date)


@tool
def get_intraday(code: str, date: str, time: str = None) -> dict:
    """获取目标股票指定日期的盘中分时（分钟级）行情，可定位到具体时间。当用户问及盘中、分时、实时、某时刻价格时调用。"""
    return tools_mod.get_intraday(code, date, time)


@tool
def get_financials(code: str, report_type: str = "资产负债表") -> dict:
    """获取目标股票的三大财务报表之一（资产负债表/利润表/现金流量表）。当用户问及财务报表、资产负债表、利润、现金流时调用。"""
    return tools_mod.get_financials(code, report_type)


@tool
def get_dividend(code: str) -> dict:
    """获取目标股票的历史分红送配方案（派息/送股/转增/股权登记日）。当用户问及分红、送股、派息、除权时调用。"""
    return tools_mod.get_dividend(code)


@tool
def get_capital_flow(code: str, market: str = None) -> dict:
    """获取目标股票个股资金流向（主力/散户净流入）。注意：当前网络环境下该接口可能不可用。当用户问及资金流向、主力资金、净流入时调用。"""
    return tools_mod.get_capital_flow(code, market)


@tool
def get_indicators(code: str, start_year: str = "2023") -> dict:
    """获取目标股票的估值与财务指标（每股收益、每股净资产、每股现金流等）。当用户问及估值、每股指标、财务分析时调用。"""
    return tools_mod.get_indicators(code, start_year)


@tool
def get_key_metrics(code: str, indicator: str = "按报告期") -> dict:
    """获取目标股票的主要财务指标摘要（营收、净利润、增长率、每股收益等）。当用户问及业绩、营收、净利、增长率时调用。"""
    return tools_mod.get_key_metrics(code, indicator)


@tool
def get_forecast(code: str, date: str = None) -> dict:
    """获取目标股票的业绩报告/预告（按报告期）。当用户问及业绩预告、季报、年报、业绩报告时调用。"""
    return tools_mod.get_forecast(code, date)


TOOLS = [
    get_profile, get_history, get_intraday, get_financials, get_dividend,
    get_capital_flow, get_indicators, get_key_metrics, get_forecast,
]

# ---------------------------------------------------------------------------
# 2. 图状态定义
# ---------------------------------------------------------------------------
if _HAVE_LANGGRAPH:
    class State(TypedDict):
        messages: Annotated[list, add_messages]
        session_id: str


# ---------------------------------------------------------------------------
# 3. 图节点
# ---------------------------------------------------------------------------
def _get_llm_with_tools():
    """惰性构建「LLM + 绑定工具」。仅在 LLM 路径首次调用时执行。"""
    if not _HAVE_LANGGRAPH:
        raise RuntimeError("未安装 langgraph / langchain，无法走 LLM 路径，请先 pip install langgraph langchain-google-genai")
    if not llm_client.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未设置")
    llm = ChatGoogleGenerativeAI(
        model=llm_client.GEMINI_MODEL,
        google_api_key=llm_client.GEMINI_API_KEY,
        temperature=0.3,
    )
    return llm.bind_tools(TOOLS)


def _agent(state: "State"):
    """agent 节点：注入系统提示 + 长期记忆，调用 LLM，返回 AIMessage。"""
    lm = mem.get_long_memory(state["session_id"])
    system_text = llm_client.SYSTEM_PROMPT
    if lm and lm.strip():
        system_text += ("\n\n【长期记忆】以下是你与该用户此前对话中已掌握的稳定信息，"
                        f"请善加利用：\n{lm.strip()}")
    sys_msg = SystemMessage(content=system_text)
    llm_with_tools = _get_llm_with_tools()
    resp = llm_with_tools.invoke([sys_msg] + state["messages"])
    return {"messages": [resp]}


def _memory_node(state: "State"):
    """memory 节点：抽取本轮工具调用事实，合并进长期记忆并持久化。"""
    facts = _extract_facts(state["messages"])
    if facts:
        mem.update_long_memory(state["session_id"], facts)
    return {}


def _should_continue(state: "State"):
    """条件边：最后一条消息仍含 tool_calls 则继续调工具，否则进入记忆节点收尾。"""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"
    return "memory"


_GRAPH = None


def _build_graph():
    global _GRAPH
    if _GRAPH is None:
        g = StateGraph(State)
        g.add_node("agent", _agent)
        g.add_node("tools", ToolNode(TOOLS))
        g.add_node("memory", _memory_node)
        g.add_edge(START, "agent")
        g.add_conditional_edges("agent", _should_continue, {"tools": "tools", "memory": "memory"})
        g.add_edge("tools", "agent")
        g.add_edge("memory", END)
        _GRAPH = g.compile(checkpointer=MemorySaver())
    return _GRAPH


# ---------------------------------------------------------------------------
# 4. 工具结果解析 / 事实抽取（供前端展示与长期记忆）
# ---------------------------------------------------------------------------
def _find_tool_result(messages, tool_call_id):
    for m in messages:
        if isinstance(m, ToolMessage) and m.tool_call_id == tool_call_id:
            try:
                return json.loads(m.content)
            except Exception:
                return {}
    return {}


def _result_summary(result):
    if not isinstance(result, dict):
        return "成功"
    if "error" in result:
        return f"失败：{result['error']}"
    if "count" in result:
        return f"成功，{result.get('count', 0)} 条"
    if "data" in result:
        return f"成功，{len(result.get('data', []))} 条"
    if "available" in result:
        return "不可用"
    return "成功"


def _summarize_fact(name, args, result):
    code = args.get("code", "")
    if not isinstance(result, dict):
        return f"已调用 {name}({code})"
    if "error" in result:
        return f"查询 {name}({code}) 失败：{result['error']}"
    if name == "get_profile":
        return f"用户关注 {result.get('name','')}({code})：{result.get('board','')}，主营 {result.get('main_business','')[:30]}"
    if name == "get_history":
        return f"已查询 {code} 历史行情 {result.get('start_date','')}~{result.get('end_date','')}，共 {result.get('count',0)} 条"
    if name == "get_intraday":
        return f"已查询 {code} 盘中行情 {result.get('date','')} {result.get('time','') or '全天'}"
    if name == "get_financials":
        return f"已查询 {code} 财务报表：{result.get('report_type','')}"
    if name == "get_dividend":
        return f"已查询 {code} 分红方案，共 {result.get('count',0)} 条"
    if name == "get_capital_flow":
        return f"查询 {code} 资金流向：当前网络不可用"
    if name == "get_indicators":
        return f"已查询 {code} 财务指标（{result.get('start_year','')} 起）"
    if name == "get_key_metrics":
        return f"已查询 {code} 主要财务摘要"
    if name == "get_forecast":
        return f"已查询 {code} 业绩报告（{result.get('date','')}）"
    return f"已调用 {name}({code})"


def _extract_facts(messages):
    """抽取「本轮（最后一条 HumanMessage 之后）」的工具调用事实，供长期记忆合并。"""
    last_human = -1
    for i, m in enumerate(messages):
        if isinstance(m, HumanMessage):
            last_human = i
    facts = []
    for m in messages[last_human + 1:]:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                name = tc["name"]
                args = tc["args"]
                result = _find_tool_result(messages, tc["id"])
                facts.append(_summarize_fact(name, args, result))
    return "\n".join(facts)


# ---------------------------------------------------------------------------
# 5. 对外入口：run_agent
# ---------------------------------------------------------------------------
def run_agent(message: str, session_id: str, long_memory: str = ""):
    """
    执行一轮对话。返回 {reply, tool_calls, chart, long_memory_facts}。
    - 有 GEMINI_API_KEY：走 LangGraph 图（agent/tools/memory 节点 + checkpointer 短期记忆）
    - 无 key：走关键词降级 _fallback_run
    """
    if not llm_client.GEMINI_API_KEY:
        return _fallback_run(message, long_memory)

    graph = _build_graph()
    cfg = {"configurable": {"thread_id": session_id}}
    try:
        result = graph.invoke(
            {"messages": [HumanMessage(content=message)], "session_id": session_id},
            config=cfg,
        )
    except Exception as e:
        return {"reply": f"LangGraph 执行失败：{e}", "tool_calls": [], "chart": None,
                "long_memory_facts": ""}

    messages = result["messages"]

    # 构建 tool_call_id -> (name, args) 映射，便于回填结果与图表
    call_map = {}
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                call_map[tc["id"]] = (tc["name"], tc["args"])

    tool_calls = []
    chart = None
    for m in messages:
        if isinstance(m, ToolMessage):
            name, args = call_map.get(m.tool_call_id, (None, None))
            try:
                data = json.loads(m.content)
            except Exception:
                data = {}
            tool_calls.append({
                "name": name, "args": args,
                "result_summary": _result_summary(data),
            })
            if name in ("get_history", "get_intraday") and isinstance(data, dict) and "error" not in data:
                chart = {"type": name, "code": args.get("code"), "data": data.get("data", [])}

    # 最终回复 = 最后一条含文本内容的 AIMessage
    reply = ""
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.content:
            reply = m.content
            break

    # 长期记忆已由 memory 节点持久化；此处返回事实用于日志/展示
    long_memory_facts = _extract_facts(messages)
    return {"reply": reply or "（无回复）", "tool_calls": tool_calls,
            "chart": chart, "long_memory_facts": long_memory_facts}


# ---------------------------------------------------------------------------
# 6. 无 LLM 时的关键词降级（与 v4 行为一致）
# ---------------------------------------------------------------------------
_LOCAL_NAME_MAP = {
    "贵州茅台": "600519", "茅台": "600519", "贵州茅台酒": "600519",
    "宁德时代": "300750", "比亚迪": "002594", "中国平安": "601318",
    "招商银行": "600036", "五粮液": "000858", "隆基绿能": "601012",
    "东方财富": "300059", "中信证券": "600030", "工商银行": "601398",
}


def _resolve_code(text):
    m = re.search(r"\b(\d{6})\b", text or "")
    if m:
        return m.group(1)
    for name, code in _LOCAL_NAME_MAP.items():
        if name in (text or ""):
            return code
    return None


def _code_from_long_memory(long_memory):
    if not long_memory:
        return None
    m = re.search(r"\((\d{6})\)", long_memory)
    return m.group(1) if m else None


def _fallback_run(message, long_memory=""):
    intent = llm_client.parse_intent(message)
    code = (intent.get("code") or _resolve_code(message)
            or _resolve_code(intent.get("name", ""))
            or _LOCAL_NAME_MAP.get(intent.get("name", ""))
            or _code_from_long_memory(long_memory))
    if not code:
        return {"reply": "未能识别股票代码或名称，请补充（如「600519」或「贵州茅台」）。",
                "tool_calls": [], "chart": None, "long_memory_facts": ""}
    tool_calls = []
    chart = None
    lines = []
    intents = intent.get("intent", [])
    if "profile" in intents:
        r = tools_mod.get_profile(code)
        tool_calls.append({"name": "get_profile", "args": {"code": code}, "result_summary": _result_summary(r)})
        if "error" not in r:
            lines.append(f"**{r.get('name', code)}（{code}）上市详情**\n- 板块：{r.get('board')}\n- 行业：{r.get('industry')}\n- 主营：{r.get('main_business')}")
    if "history" in intents:
        s = (intent.get("start_date") or intent.get("date") or "").replace("-", "") or "20240101"
        e = (intent.get("end_date") or intent.get("date") or "").replace("-", "") or datetime.date.today().strftime("%Y%m%d")
        r = tools_mod.get_history(code, s, e)
        tool_calls.append({"name": "get_history", "args": {"code": code, "start_date": s, "end_date": e}, "result_summary": _result_summary(r)})
        if "error" not in r:
            chart = {"type": "get_history", "code": code, "data": r.get("data", [])}
            lines.append(f"**历史行情（{s}~{e}，{r.get('count',0)} 条）**")
    if "intraday" in intents:
        d = intent.get("date") or datetime.date.today().strftime("%Y-%m-%d")
        r = tools_mod.get_intraday(code, d, intent.get("time"))
        tool_calls.append({"name": "get_intraday", "args": {"code": code, "date": d, "time": intent.get("time")}, "result_summary": _result_summary(r)})
        if "error" not in r:
            chart = {"type": "get_intraday", "code": code, "data": r.get("data", [])}
            lines.append(f"**盘中行情（{d}）**")
    facts = "\n".join(_summarize_fact(t["name"], t["args"], tools_mod.TOOL_FUNCTIONS[t["name"]](**t["args"])) for t in tool_calls)
    return {"reply": "\n\n".join(lines) or "未获取到信息。", "tool_calls": tool_calls,
            "chart": chart, "long_memory_facts": facts}
