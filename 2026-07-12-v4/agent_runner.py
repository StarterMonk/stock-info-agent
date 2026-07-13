"""
v4 Agent 执行层：LLM 主导 + 工具调用闭环 + 多轮记忆。

run_agent(message, history, long_memory) 流程：
1. 组装 contents：长期记忆(作为 user 前置上下文) + 短期历史(最近 N 轮) + 当前用户消息
2. 调用 llm_client.generate(contents, tools=TOOL_DECLARATIONS)
3. 若返回含 functionCall：执行工具 -> 把 functionResponse 追加进 contents -> 再次 generate
4. 循环直到返回纯文本（最多 MAX_TOOL_ROUNDS 轮）
5. 返回 {reply, tool_calls, chart, long_memory_facts}
   - tool_calls: 本轮调用的工具名+参数+结果摘要（供前端展示进度）
   - chart: 若工具返回了可绘图数据（history/intraday），附带供前端渲染
"""
import re
import datetime
import llm_client
import tools as tools_mod
from tools import TOOL_DECLARATIONS, call_tool

MAX_TOOL_ROUNDS = 5

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


def _build_contents(history, long_memory, message):
    """构造多轮 contents。history: [{role, parts:[{text}]}] 已含 functionCall/Response。"""
    contents = []
    if long_memory and long_memory.strip():
        contents.append({
            "role": "user",
            "parts": [{"text": f"【长期记忆】以下是你与该用户此前对话中已掌握的稳定信息，请善加利用：\n{long_memory.strip()}"}],
        })
        contents.append({
            "role": "model",
            "parts": [{"text": "已了解上述长期记忆，会在后续回答中结合使用。"}],
        })
    contents.extend(history or [])
    contents.append({"role": "user", "parts": [{"text": message}]})
    return contents


def _extract_function_call(content):
    for p in content.get("parts", []):
        if "functionCall" in p:
            fc = p["functionCall"]
            return fc.get("name"), fc.get("args", {})
    return None


def _text_of(content):
    return "".join(p.get("text", "") for p in content.get("parts", []) if "text" in p)


def _summarize_fact(name, args, result):
    code = args.get("code", "")
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


def run_agent(message, history=None, long_memory=""):
    """LLM 主导 + 工具调用。返回 dict。"""
    if not llm_client.GEMINI_API_KEY:
        return _fallback_run(message, long_memory)

    contents = _build_contents(history, long_memory, message)
    tool_calls = []
    chart = None
    last_content = None
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            content = llm_client.generate(contents, tools=TOOL_DECLARATIONS, temperature=0.3)
        except Exception as e:
            return {"reply": f"LLM 调用失败：{e}", "tool_calls": tool_calls, "chart": chart,
                    "long_memory_facts": ""}
        last_content = content
        fc = _extract_function_call(content)
        if not fc:
            break
        name, args = fc
        if "code" in args and not args.get("code"):
            code = _resolve_code(message) or _resolve_code(long_memory)
            if code:
                args["code"] = code
        result = call_tool(name, args)
        tool_calls.append({"name": name, "args": args, "result_summary": _result_summary(result)})
        if name in ("get_history", "get_intraday") and "error" not in result:
            chart = {"type": name, "code": args.get("code"), "data": result.get("data", [])}
        contents.append({"role": "model", "parts": content.get("parts", [])})
        contents.append({
            "role": "user",
            "parts": [{"functionResponse": {"name": name, "response": {"result": result}}}],
        })

    reply = _text_of(last_content) if last_content else "（无回复）"
    facts = "\n".join(_summarize_fact(t["name"], t["args"], call_tool(t["name"], t["args"])) for t in tool_calls)
    return {"reply": reply, "tool_calls": tool_calls, "chart": chart, "long_memory_facts": facts}


def _code_from_long_memory(long_memory):
    """从长期记忆文本中提取已关注股票代码（如 '贵州茅台(600519)'）。"""
    if not long_memory:
        return None
    m = re.search(r"\((\d{6})\)", long_memory)
    return m.group(1) if m else None


def _result_summary(result):
    if "error" in result:
        return f"失败：{result['error']}"
    if "count" in result:
        return f"成功，{result.get('count', 0)} 条"
    if "data" in result:
        return f"成功，{len(result.get('data', []))} 条"
    if "available" in result:
        return "不可用"
    return "成功"


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
        r = call_tool("get_profile", {"code": code})
        tool_calls.append({"name": "get_profile", "args": {"code": code}, "result_summary": _result_summary(r)})
        if "error" not in r:
            lines.append(f"**{r.get('name', code)}（{code}）上市详情**\n- 板块：{r.get('board')}\n- 行业：{r.get('industry')}\n- 主营：{r.get('main_business')}")
    if "history" in intents:
        s = (intent.get("start_date") or intent.get("date") or "").replace("-", "") or "20240101"
        e = (intent.get("end_date") or intent.get("date") or "").replace("-", "") or datetime.date.today().strftime("%Y%m%d")
        r = call_tool("get_history", {"code": code, "start_date": s, "end_date": e})
        tool_calls.append({"name": "get_history", "args": {"code": code, "start_date": s, "end_date": e}, "result_summary": _result_summary(r)})
        if "error" not in r:
            chart = {"type": "get_history", "code": code, "data": r.get("data", [])}
            lines.append(f"**历史行情（{s}~{e}，{r.get('count',0)} 条）**")
    if "intraday" in intents:
        d = intent.get("date") or datetime.date.today().strftime("%Y-%m-%d")
        r = call_tool("get_intraday", {"code": code, "date": d, "time": intent.get("time")})
        tool_calls.append({"name": "get_intraday", "args": {"code": code, "date": d, "time": intent.get("time")}, "result_summary": _result_summary(r)})
        if "error" not in r:
            chart = {"type": "get_intraday", "code": code, "data": r.get("data", [])}
            lines.append(f"**盘中行情（{d}）**")
    facts = "\n".join(_summarize_fact(t["name"], t["args"], call_tool(t["name"], t["args"])) for t in tool_calls)
    return {"reply": "\n\n".join(lines) or "未获取到信息。", "tool_calls": tool_calls,
            "chart": chart, "long_memory_facts": facts}
