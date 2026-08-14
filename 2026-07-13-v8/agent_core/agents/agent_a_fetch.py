"""
Agent A：数据获取智能体。
根据 data_requests 从 AKShare 获取原始数据，写入 raw_data。
支持 C → A 回路：补充数据时合并到已有 raw_data。
"""
import logging
import tools as tools_mod

logger = logging.getLogger(__name__)

_result_summary = tools_mod.result_summary


def agent_a_fetch_node(state: dict) -> dict:
    """
    执行数据获取：遍历 data_requests，逐个调用工具函数，
    将结果汇总到 raw_data 字典。

    如果是 C 请求补充数据（c_retry_count > 0），合并到已有 raw_data。
    """
    requests = state.get("data_requests", [])
    if not requests:
        return {"raw_data": {}, "current_step": "agent_a_done"}

    # 如果是 C → A 回路，保留已有数据
    c_retry = state.get("c_retry_count", 0)
    existing_raw = state.get("raw_data", {}) if c_retry > 0 else {}
    existing_calls = state.get("all_tool_calls", []) if c_retry > 0 else []

    raw_data = dict(existing_raw)
    tool_calls = list(existing_calls)

    for req in requests:
        tool_name = req.get("tool", "")
        args = req.get("args", {})
        try:
            result = tools_mod.call_tool(tool_name, args)
            raw_data[tool_name] = result
            tool_calls.append({
                "name": tool_name,
                "args": args,
                "result_summary": _result_summary(result),
            })
        except Exception as e:
            logger.error("Agent A 工具调用失败 %s: %s", tool_name, e)
            raw_data[tool_name] = {"error": str(e)}
            tool_calls.append({
                "name": tool_name,
                "args": args,
                "result_summary": f"失败：{e}",
            })

    # C → A 回路完成后，重置 needs_more_data
    return {
        "raw_data": raw_data,
        "all_tool_calls": tool_calls,
        "needs_more_data": False,
        "current_step": "agent_a_done",
    }
