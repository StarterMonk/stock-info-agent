"""
超级节点：LLM 驱动的路由中心。
解析用户意图 → 提取股票代码 → 决定执行流程（哪些智能体参与）。
"""
import re
import datetime
import logging

import llm_client
import stock_search
import tools as tools_mod

logger = logging.getLogger(__name__)

_LOCAL_NAME_MAP = tools_mod._LOCAL_NAME_MAP


def _resolve_code(text: str) -> str:
    """从文本中提取 6 位股票代码。"""
    match = re.search(r"\b(\d{6})\b", text or "")
    if match:
        return match.group(1)
    for name, code in _LOCAL_NAME_MAP.items():
        if name in (text or ""):
            return code
    try:
        return stock_search.resolve(text or "")
    except Exception:
        return ""


def _resolve_code_from_name(name: str) -> str:
    """从股票名称解析代码。"""
    if not name:
        return ""
    if name in _LOCAL_NAME_MAP:
        return _LOCAL_NAME_MAP[name]
    try:
        hits = stock_search.lookup(name, top_k=1)
        if hits and hits[0]["score"] >= 0.06:
            return hits[0]["code"]
    except Exception:
        pass
    return ""


def supervisor_node(state: dict) -> dict:
    """
    超级节点：解析用户意图，决定执行路径。
    返回 next_agent / needs_processing / needs_chart / complexity / ticker / stock_name。
    """
    query = state.get("user_query", "")
    if not query:
        return {"next_agent": "end", "final_reply": "请输入您的问题。"}

    # 1. 解析股票代码
    code = state.get("ticker", "") or _resolve_code(query)
    if not code:
        intent = llm_client.parse_intent(query)
        code = (intent.get("code", "")
                or _resolve_code(intent.get("name", ""))
                or _LOCAL_NAME_MAP.get(intent.get("name", "")))
    if not code:
        return {
            "next_agent": "end",
            "final_reply": "未能识别股票代码或名称，请补充（如「600519」或「贵州茅台」）。",
        }

    # 2. 获取股票名称
    stock_name = state.get("stock_name", "")
    if not stock_name:
        try:
            stock_name = stock_search.get_name(code) or code
        except Exception:
            stock_name = code

    # 3. 解析意图
    intent = llm_client.parse_intent(query)
    intents = intent.get("intent", [])

    # 4. 判断需要哪些智能体
    needs_processing = any(k in intents for k in [
        "prediction", "technical_indicators", "forecast",
    ])
    needs_chart = any(k in intents for k in [
        "history", "intraday", "prediction",
    ]) or needs_chart_keyword(query)

    # 如果有数据请求（历史行情），默认需要图表
    if not needs_chart and not needs_processing:
        # 简单查询也生成图表（有数据就能画）
        needs_chart = True

    # 简单查询（仅公司资料/财务摘要）→ 只需 Agent A
    simple = not needs_processing and not needs_chart
    if simple and "profile" in intents and len(intents) == 1:
        needs_processing = False
        needs_chart = False

    # 5. 检测分析复杂度
    complexity = _detect_complexity(query)

    # 6. 构建 Agent A 的数据请求
    data_requests = _build_data_requests(code, intents, intent)

    return {
        "ticker": code,
        "stock_name": stock_name,
        "next_agent": "agent_a",
        "needs_processing": needs_processing,
        "needs_chart": needs_chart,
        "complexity": complexity,
        "data_requests": data_requests,
        "current_step": "supervisor_done",
    }


def _detect_complexity(query: str) -> str:
    """
    根据用户关键词检测分析复杂度。
    - 默认：simple（简单方法）
    - 中等关键词：中等方法
    - 复杂关键词：复杂方法
    """
    q = query.lower()

    # 复杂方法关键词
    complex_keywords = [
        "ai预测", "ai 预测", "深度学习", "高级分析", "高级预测",
        "神经网络", "lstm", "transformer", "deep learning",
        "最精确", "最准确", "最强", "最好的方法",
    ]
    for kw in complex_keywords:
        if kw in q:
            return "complex"

    # 中等方法关键词
    medium_keywords = [
        "深度分析", "详细分析", "详细预测", "精确分析", "精确预测",
        "机器学习", "xgboost", "lightgbm", "garch", "统计模型",
        "专业分析", "专业预测", "量化分析", "量化预测",
    ]
    for kw in medium_keywords:
        if kw in q:
            return "medium"

    return "simple"


def needs_chart_keyword(query: str) -> bool:
    """关键词判断是否需要作图。"""
    keywords = ["图", "K线", "k线", "曲线", "走势", "行情", "可视化", "画", "图表", "柱状"]
    return any(k in query for k in keywords)


def _build_data_requests(code: str, intents: list, intent: dict) -> list:
    """根据意图构建 Agent A 的数据请求列表。"""
    requests = []

    if "profile" in intents:
        requests.append({"tool": "get_profile", "args": {"code": code}})

    if "history" in intents:
        start = (intent.get("start_date") or intent.get("date") or "").replace("-", "")
        end = (intent.get("end_date") or intent.get("date") or "").replace("-", "")
        if not start:
            start = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y%m%d")
        if not end:
            end = datetime.date.today().strftime("%Y%m%d")
        requests.append({
            "tool": "get_history",
            "args": {"code": code, "start_date": start, "end_date": end},
        })

    if "intraday" in intents:
        day = intent.get("date") or datetime.date.today().strftime("%Y-%m-%d")
        requests.append({
            "tool": "get_intraday",
            "args": {"code": code, "date": day, "time": intent.get("time", "")},
        })

    if "financials" in intents:
        requests.append({"tool": "get_financials", "args": {"code": code}})

    if "dividend" in intents:
        requests.append({"tool": "get_dividend", "args": {"code": code}})

    if "indicators" in intents:
        requests.append({"tool": "get_indicators", "args": {"code": code}})

    if "key_metrics" in intents:
        requests.append({"tool": "get_key_metrics", "args": {"code": code}})

    if "forecast" in intents:
        requests.append({"tool": "get_forecast", "args": {"code": code}})

    if "technical_indicators" in intents:
        requests.append({"tool": "get_technical_indicators", "args": {"code": code}})

    if "prediction" in intents:
        requests.append({"tool": "get_price_prediction", "args": {"code": code, "horizon": 10}})

    # 默认：至少获取公司资料 + 历史行情
    if not requests:
        requests.append({"tool": "get_profile", "args": {"code": code}})
        requests.append({
            "tool": "get_history",
            "args": {
                "code": code,
                "start_date": (datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y%m%d"),
                "end_date": datetime.date.today().strftime("%Y%m%d"),
            },
        })

    return requests
