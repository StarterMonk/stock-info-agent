"""
LangGraph 图构建：StateGraph + 条件路由 + 重试策略。
"""
import json
from langgraph.graph import StateGraph, START, END
from langgraph.types import RetryPolicy

from agents.supervisor import supervisor_node
from agents.agent_a_fetch import agent_a_fetch_node
from agents.agent_b_chart import agent_b_chart_node
from agents.agent_c_process import agent_c_process_node

# 重试策略：5 次重试，指数退避
_RETRY = RetryPolicy(
    max_attempts=5,
    initial_interval=1.0,
    backoff_factor=2.0,
    max_interval=30.0,
    jitter=True,
)


def _route_after_supervisor(state: dict) -> str:
    """超级节点路由：根据 next_agent 决定走向。"""
    next_agent = state.get("next_agent", "end")
    if next_agent == "end":
        return "end"
    if next_agent == "agent_a":
        return "agent_a"
    return "end"


def _route_after_fetch(state: dict) -> str:
    """Agent A 完成后路由。"""
    # C → A 回路：A 补数据后回到 C
    if state.get("c_retry_count", 0) > 0:
        return "agent_c"

    needs_processing = state.get("needs_processing", False)
    needs_chart = state.get("needs_chart", False)

    if needs_processing:
        return "agent_c"
    if needs_chart:
        return "agent_b"
    return "assembler"


def _route_after_process(state: dict) -> str:
    """Agent C 完成后路由。"""
    # C 请求补充数据 → 回到 Agent A
    if state.get("needs_more_data"):
        return "agent_a"

    # 检查是否有未解决的异常（需要用户交互）
    anomaly_flags = state.get("anomaly_flags", [])
    anomaly_resolutions = state.get("anomaly_resolutions", {})
    unresolved = [a for a in anomaly_flags
                  if a.get("id") not in anomaly_resolutions]
    if unresolved:
        return "anomaly_handler"

    if state.get("needs_chart", False):
        return "agent_b"
    return "assembler"


def _route_after_anomaly(state: dict) -> str:
    """异常处理后回到 Agent C 继续处理。"""
    return "agent_c"


def _assembler_node(state: dict) -> dict:
    """最终组装：将各智能体的输出组合成分类回复（### 分类头供前端 categorize 拆分）。"""
    raw_data = state.get("raw_data", {})
    prediction = state.get("prediction", {})
    processed = state.get("processed_data", {})
    charts = state.get("charts", [])
    stock_name = state.get("stock_name", "")
    ticker = state.get("ticker", "")
    complexity = state.get("complexity", "simple")

    sections = []

    # ── 概况 ──
    profile = raw_data.get("get_profile", {})
    if isinstance(profile, dict) and "error" not in profile:
        sections.append(
            f"### 公司概况\n"
            f"**{profile.get('name', ticker)}（{ticker}）**\n"
            f"- 板块：{profile.get('board', '')}\n"
            f"- 行业：{profile.get('industry', '')}\n"
            f"- 主营：{profile.get('main_business', '')[:80]}"
        )

    # ── 行情 ──
    history = raw_data.get("get_history", {})
    if isinstance(history, dict) and "error" not in history:
        count = history.get("count", 0)
        data = history.get("data", [])
        if data:
            latest = data[-1]
            sections.append(
                f"### 行情数据\n"
                f"共 {count} 个交易日，最新收盘 **{latest.get('close')}**\n"
                f"- 开盘 {latest.get('open')} / 最高 {latest.get('high')} / 最低 {latest.get('low')}\n"
                f"- 成交量 {latest.get('volume')}"
            )

    # ── 技术指标（分析）──
    tech = raw_data.get("get_technical_indicators", {})
    if isinstance(tech, dict) and "error" not in tech:
        sections.append(
            f"### 技术分析\n"
            f"- 趋势：{tech.get('trend_state', '未知')}\n"
            f"- MACD：{tech.get('macd_relation', '未知')}\n"
            f"- RSI(14)：{tech.get('rsi_14', '未知')}\n"
            f"- 支撑位 {tech.get('support_level', '-')} / 压力位 {tech.get('resistance_level', '-')}"
        )

    # ── 预测 ──
    if prediction and "error" not in prediction:
        direction = prediction.get("direction", "")
        score = prediction.get("direction_score", "")
        forecasts = prediction.get("forecasts", [])
        method = prediction.get("method_used", "")
        fc_lines = "\n".join(
            f"  - T+{f['horizon_days']}：**{f['median_price']}** 元"
            for f in forecasts
        )
        sections.append(
            f"### 价格预测\n"
            f"- 方向：{direction}（上涨概率 {score}）\n"
            f"- 方法：{method}（{complexity}级别）\n"
            f"- 支撑位 {prediction.get('support_level', '-')} / 压力位 {prediction.get('resistance_level', '-')}\n"
            f"{fc_lines}"
        )

    # ── 财务 ──
    financials = raw_data.get("get_financials", {})
    if isinstance(financials, dict) and "error" not in financials:
        sections.append(f"### 财务数据\n{json.dumps(financials, ensure_ascii=False)[:300]}")

    # ── 公告 ──
    forecast_data = raw_data.get("get_forecast", {})
    if isinstance(forecast_data, dict) and "error" not in forecast_data:
        sections.append(f"### 公告与预告\n{json.dumps(forecast_data, ensure_ascii=False)[:300]}")

    final_reply = "\n\n".join(sections) or "未获取到信息。"
    final_chart = charts[0] if charts else {}

    return {
        "final_reply": final_reply,
        "final_chart": final_chart,
        "current_step": "done",
    }


def build_graph():
    """构建并编译 LangGraph 多智能体图。"""
    from graph_state import StockState

    builder = StateGraph(StockState)

    # 添加节点
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("agent_a", agent_a_fetch_node, retry=_RETRY)
    builder.add_node("agent_c", agent_c_process_node, retry=_RETRY)
    builder.add_node("agent_b", agent_b_chart_node, retry=_RETRY)
    builder.add_node("anomaly_handler", _anomaly_handler_node)
    builder.add_node("assembler", _assembler_node)

    # 入口 → 超级节点
    builder.add_edge(START, "supervisor")

    # 超级节点条件路由
    builder.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {
            "agent_a": "agent_a",
            "end": "assembler",
        },
    )

    # Agent A 完成后条件路由
    builder.add_conditional_edges(
        "agent_a",
        _route_after_fetch,
        {
            "agent_c": "agent_c",
            "agent_b": "agent_b",
            "assembler": "assembler",
        },
    )

    # Agent C 完成后条件路由
    builder.add_conditional_edges(
        "agent_c",
        _route_after_process,
        {
            "agent_a": "agent_a",       # C → A 补数据
            "anomaly_handler": "anomaly_handler",
            "agent_b": "agent_b",
            "assembler": "assembler",
        },
    )

    # 异常处理后回到 Agent C
    builder.add_conditional_edges(
        "anomaly_handler",
        _route_after_anomaly,
        {"agent_c": "agent_c"},
    )

    # Agent B → 组装器 → 结束
    builder.add_edge("agent_b", "assembler")
    builder.add_edge("assembler", END)

    return builder.compile()


def _anomaly_handler_node(state: dict) -> dict:
    """
    异常处理节点：自动应用默认处理策略（forward_fill / cap_at_limit），
    避免无限循环。用户可通过 API 覆盖。
    """
    anomaly_flags = state.get("anomaly_flags", [])
    resolutions = dict(state.get("anomaly_resolutions", {}))

    for flag in anomaly_flags:
        aid = flag.get("id", "")
        if aid not in resolutions:
            resolutions[aid] = flag.get("default_action", "forward_fill")

    return {
        "anomaly_resolutions": resolutions,
        "current_step": "anomaly_handled",
    }
