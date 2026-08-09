"""
v7-openrouter Agent 执行层：基于 OpenRouter Chat Completions 的「意图 → 工具调用闭环」引擎。

与 v7（LangGraph 编排）的区别：
- 不依赖 langgraph / langchain：LLM 由 llm_client.chat() 直连 OpenRouter REST 接口；
- 多轮工具调用由本模块手写循环驱动（最多 MAX_TOOL_ROUNDS 轮），
  消息体与返回参数全部采用 OpenAI 兼容格式（tool_calls / tool 角色消息）；
- 短期记忆直接复用 session_store（SQLite），长期记忆复用 memory_store；
- 无 OPENROUTER_API_KEY 时自动降级为关键词模式（与 v7 一致）。
"""
import re
import json
import datetime
import logging

import llm_client
import tools as tools_mod
import session_store as store
import memory_store as mem

logger = logging.getLogger(__name__)

_LOCAL_NAME_MAP = tools_mod._LOCAL_NAME_MAP

MAX_TOOL_ROUNDS = 6
_CHART_HISTORY = 8  # 参与上下文的历史消息条数


# ---------------------------------------------------------------------------
# 1. 工具声明：OpenAI 格式（OpenRouter 使用 {"type":"function","function":{...}}）
# ---------------------------------------------------------------------------
def _openai_tools() -> list:
    return [{"type": "function", "function": declaration}
            for declaration in tools_mod.TOOL_DECLARATIONS]


# ---------------------------------------------------------------------------
# 2. 工具结果解析 / 事实抽取（与 v7 语义一致）
# ---------------------------------------------------------------------------
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
        return f"用户关注 {result.get('name', '')}({code})：{result.get('board', '')}，主营 {result.get('main_business', '')[:30]}"
    if name == "get_history":
        return f"已查询 {code} 历史行情 {result.get('start_date', '')}~{result.get('end_date', '')}，共 {result.get('count', 0)} 条"
    if name == "get_intraday":
        return f"已查询 {code} 盘中行情 {result.get('date', '')} {result.get('time', '') or '全天'}"
    if name == "get_financials":
        return f"已查询 {code} 财务报表：{result.get('report_type', '')}"
    if name == "get_dividend":
        return f"已查询 {code} 分红方案，共 {result.get('count', 0)} 条"
    if name == "get_capital_flow":
        return f"查询 {code} 资金流向：当前网络不可用"
    if name == "get_indicators":
        return f"已查询 {code} 财务指标（{result.get('start_year', '')} 起）"
    if name == "get_key_metrics":
        return f"已查询 {code} 主要财务摘要"
    if name == "get_forecast":
        return f"已查询 {code} 业绩报告（{result.get('date', '')}）"
    if name == "get_technical_indicators":
        return f"已查询 {code} 技术指标：{result.get('trend_state', '')}状态"
    if name == "get_price_prediction":
        return (f"已预测 {code}：{result.get('direction', '')}（上涨概率 "
                f"{result.get('direction_score', '')}），支撑 {result.get('support_level', '')}"
                f" / 压力 {result.get('resistance_level', '')}")
    return f"已调用 {name}({code})"


# ---------------------------------------------------------------------------
# 3. 图表提取：优先价格预测，其次 K 线/分时
# ---------------------------------------------------------------------------
def _build_chart(metas):
    chart = None
    for meta in reversed(metas):
        name = meta["name"]
        result = meta.get("result", {})
        args = meta.get("args", {})
        if name == "get_price_prediction" and isinstance(result, dict) and "error" not in result:
            return {"type": "get_price_prediction", "code": args.get("code", ""),
                    "current_price": result.get("current_price"),
                    "forecasts": result.get("forecasts", []),
                    "direction": result.get("direction"),
                    "direction_score": result.get("direction_score"),
                    "support_level": result.get("support_level"),
                    "resistance_level": result.get("resistance_level")}
        if name in ("get_history", "get_intraday") and isinstance(result, dict) and "error" not in result:
            chart = {"type": name, "code": args.get("code"), "data": result.get("data", [])}
    return chart


# ---------------------------------------------------------------------------
# 4. 对外入口：run_agent（LLM 路径 = OpenRouter 工具调用闭环）
# ---------------------------------------------------------------------------
def run_agent(message: str, session_id: str, long_memory: str = ""):
    """
    执行一轮对话。返回 {reply, tool_calls, chart, long_memory_facts}。
    - 有 OPENROUTER_API_KEY：OpenRouter 工具调用闭环
    - 无 key：关键词降级 _fallback_run
    """
    if not llm_client.has_api_key():
        return _fallback_run(message, long_memory)

    # 短期记忆：从 SQLite 会话读取最近消息，重建 OpenAI 格式上下文
    history = store.get_messages(session_id)[-_CHART_HISTORY * 2:]
    messages = [{"role": "user" if item["role"] == "user" else "assistant",
                 "content": item["content"]}
                for item in history if item["role"] in ("user", "assistant")]
    messages.append({"role": "user", "content": message})

    system_prompt = llm_client.SYSTEM_PROMPT
    lm = mem.get_long_memory(session_id)
    if lm and lm.strip():
        system_prompt += ("\n\n【长期记忆】以下是你与该用户此前对话中已掌握的稳定信息，"
                          f"请善加利用：\n{lm.strip()}")

    metas = []
    reply = ""
    try:
        for _ in range(MAX_TOOL_ROUNDS):
            response = llm_client.chat(system_prompt, messages,
                                       tools=_openai_tools(), temperature=0.3)
            calls = response.get("tool_calls") or []
            if not calls:
                reply = (response.get("content") or "").strip() or "（无回复）"
                break
            for call in calls:
                name = call.get("name", "")
                args = call.get("arguments") or {}
                if not name:
                    continue
                result = tools_mod.call_tool(name, args)
                metas.append({"name": name, "args": args, "result": result,
                              "result_summary": _result_summary(result)})
                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": call.get("id", ""),
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
                    }],
                })
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "content": json.dumps(result, ensure_ascii=False)})
    except Exception as exc:
        logger.error("OpenRouter 调用失败，降级关键词模式：%s", exc)
        return _fallback_run(message, long_memory)

    if not reply:
        reply = "工具调用轮次已达上限，请尝试简化问题后再问。"

    facts = "\n".join(_summarize_fact(m["name"], m["args"], m["result"]) for m in metas)
    if facts:
        mem.update_long_memory(session_id, facts)

    tool_calls = [{"name": m["name"], "args": m["args"], "result_summary": m["result_summary"]}
                  for m in metas]
    return {"reply": reply, "tool_calls": tool_calls,
            "chart": _build_chart(metas), "long_memory_facts": facts}


# ---------------------------------------------------------------------------
# 5. 无 LLM 时的关键词降级（与 v7 行为一致）
# ---------------------------------------------------------------------------
def _resolve_code(text):
    match = re.search(r"\b(\d{6})\b", text or "")
    if match:
        return match.group(1)
    for name, code in _LOCAL_NAME_MAP.items():
        if name in (text or ""):
            return code
    return None


def _code_from_long_memory(long_memory):
    if not long_memory:
        return None
    match = re.search(r"\((\d{6})\)", long_memory)
    return match.group(1) if match else None


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
    results = []
    lines = []
    chart = None
    intents = intent.get("intent", [])
    if "profile" in intents:
        result = tools_mod.get_profile(code)
        tool_calls.append({"name": "get_profile", "args": {"code": code}, "result_summary": _result_summary(result)})
        results.append(("get_profile", {"code": code}, result))
        if "error" not in result:
            lines.append(f"**{result.get('name', code)}（{code}）上市详情**\n"
                         f"- 板块：{result.get('board')}\n- 行业：{result.get('industry')}\n"
                         f"- 主营：{result.get('main_business')}")
    if "history" in intents:
        start = (intent.get("start_date") or intent.get("date") or "").replace("-", "") or "20240101"
        end = (intent.get("end_date") or intent.get("date") or "").replace("-", "") or datetime.date.today().strftime("%Y%m%d")
        result = tools_mod.get_history(code, start, end)
        tool_calls.append({"name": "get_history", "args": {"code": code, "start_date": start, "end_date": end},
                           "result_summary": _result_summary(result)})
        results.append(("get_history", {"code": code, "start_date": start, "end_date": end}, result))
        if "error" not in result:
            chart = {"type": "get_history", "code": code, "data": result.get("data", [])}
            lines.append(f"**历史行情（{start}~{end}，{result.get('count', 0)} 条）**")
    if "intraday" in intents:
        day = intent.get("date") or datetime.date.today().strftime("%Y-%m-%d")
        result = tools_mod.get_intraday(code, day, intent.get("time"))
        tool_calls.append({"name": "get_intraday", "args": {"code": code, "date": day, "time": intent.get("time")},
                           "result_summary": _result_summary(result)})
        results.append(("get_intraday", {"code": code, "date": day, "time": intent.get("time")}, result))
        if "error" not in result:
            chart = {"type": "get_intraday", "code": code, "data": result.get("data", [])}
            lines.append(f"**盘中行情（{day}）**")
    if "prediction" in intents:
        result = tools_mod.get_price_prediction(code, 10)
        tool_calls.append({"name": "get_price_prediction", "args": {"code": code, "horizon": 10},
                           "result_summary": _result_summary(result)})
        results.append(("get_price_prediction", {"code": code, "horizon": 10}, result))
        if "error" not in result:
            chart = {"type": "get_price_prediction", "code": code,
                     "current_price": result.get("current_price"), "forecasts": result.get("forecasts", []),
                     "direction": result.get("direction"), "direction_score": result.get("direction_score"),
                     "support_level": result.get("support_level"), "resistance_level": result.get("resistance_level")}
            lines.append(f"**价格预测（{code}）**：方向 {result.get('direction')}"
                         f"（上涨概率 {result.get('direction_score')}），支撑位 {result.get('support_level')}，"
                         f"压力位 {result.get('resistance_level')}。未来多周期区间见图表。"
                         f"预测仅供参考，不构成投资建议。")
    if "technical_indicators" in intents:
        result = tools_mod.get_technical_indicators(code)
        tool_calls.append({"name": "get_technical_indicators", "args": {"code": code},
                           "result_summary": _result_summary(result)})
        results.append(("get_technical_indicators", {"code": code}, result))
        if "error" not in result:
            lines.append(f"**技术指标（{code}）**：{result.get('trend_state')}状态，"
                         f"MACD {result.get('macd_relation')}，RSI {result.get('rsi_14')}"
                         f"（超买{'是' if result.get('overbought') else '否'}"
                         f"/超卖{'是' if result.get('oversold') else '否'}），"
                         f"支撑 {result.get('support_level')} / 压力 {result.get('resistance_level')}。")
    facts = "\n".join(_summarize_fact(n, a, r) for n, a, r in results)
    return {"reply": "\n\n".join(lines) or "未获取到信息。", "tool_calls": tool_calls,
            "chart": chart, "long_memory_facts": facts}