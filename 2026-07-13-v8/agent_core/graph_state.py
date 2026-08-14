"""
多智能体共享状态定义（LangGraph StateGraph）。
所有智能体通过读写同一份 TypedDict 通信，无消息传递。
"""
from typing import TypedDict, Any, Optional, Annotated
from langgraph.graph import add_messages


class StockState(TypedDict, total=False):
    # ── 对话历史 ──
    messages: Annotated[list, add_messages]

    # ── 用户输入 ──
    user_query: str
    session_id: str

    # ── 股票标识 ──
    ticker: str
    stock_name: str

    # ── Agent A 输出 ──
    raw_data: dict           # {profile, history, financials, indicators, ...}
    data_requests: list      # Agent C → A 的补充数据请求 [{tool, args}]

    # ── Agent C 输出 ──
    processed_data: dict     # 清洗/验证后的数据
    prediction: dict         # 模型预测结果
    anomaly_flags: list      # 检测到的异常 [{type, description, severity}]
    anomaly_resolutions: dict # 用户对异常的处理决定 {anomaly_id: choice}
    data_sufficient: bool    # 数据是否足够

    # ── Agent B 输出 ──
    chart_data: dict         # 图表渲染数据
    charts: list             # 生成的图表列表

    # ── 协调控制 ──
    current_step: str        # 当前执行步骤
    next_agent: str          # 超级节点指定的下一个智能体
    needs_processing: bool   # 是否需要 Agent C 处理
    needs_chart: bool        # 是否需要 Agent B 作图
    needs_more_data: bool    # Agent C → A 数据回路标记
    c_retry_count: int       # C → A 回路计数（防无限循环，上限 2）
    complexity: str          # 分析方法复杂度: simple / medium / complex
    error_log: list          # 错误记录 [{agent, error, attempt}]

    # ── 最终输出 ──
    final_reply: str         # 组装好的最终回复
    final_chart: dict        # 组装好的最终图表数据
    all_tool_calls: list     # 所有工具调用记录
