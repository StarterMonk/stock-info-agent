"""
Agent B：图表生成智能体。
根据 raw_data / processed_data / prediction 生成对应的图表数据。
"""
import logging

logger = logging.getLogger(__name__)


def agent_b_chart_node(state: dict) -> dict:
    """
    根据数据类型生成对应的 ECharts 图表数据。
    支持：K线图、预测图、技术指标图。
    """
    raw_data = state.get("raw_data", {})
    prediction = state.get("prediction", {})
    processed = state.get("processed_data", {})
    ticker = state.get("ticker", "")
    stock_name = state.get("stock_name", ticker)

    charts = []

    # 1. K线图（历史行情数据）
    history = raw_data.get("get_history", {})
    if isinstance(history, dict) and "error" not in history:
        data = history.get("data", [])
        if data:
            charts.append(_build_candlestick(data, ticker, stock_name))

    # 2. 预测图
    if prediction and "error" not in prediction:
        charts.append(_build_prediction_chart(prediction, ticker, stock_name))

    # 3. 技术指标图
    tech = raw_data.get("get_technical_indicators", {})
    if isinstance(tech, dict) and "error" not in tech:
        # 技术指标图需要历史数据 + 指标
        if isinstance(history, dict) and "error" not in history:
            hist_data = history.get("data", [])
            if hist_data:
                charts.append(_build_technical_chart(hist_data, tech, ticker, stock_name))

    return {
        "charts": charts,
        "current_step": "agent_b_done",
    }


def _build_candlestick(data: list, ticker: str, stock_name: str) -> dict:
    """构建 K 线图（ECharts candlestick）。"""
    dates = [d.get("date", "") for d in data]
    ohlc = [[d.get("open"), d.get("close"), d.get("low"), d.get("high")] for d in data]
    volumes = [d.get("volume", 0) for d in data]

    # 计算 MA5 / MA20
    closes = [float(d.get("close", 0)) for d in data]
    ma5 = _moving_average(closes, 5)
    ma10 = _moving_average(closes, 10)
    ma20 = _moving_average(closes, 20)

    series = [
        {
            "name": "K线",
            "type": "candlestick",
            "data": ohlc,
        },
        {
            "name": "MA5",
            "type": "line",
            "data": ma5,
            "lineStyle": {"width": 1},
            "itemStyle": {"color": "#ff6600"},
        },
        {
            "name": "MA10",
            "type": "line",
            "data": ma10,
            "lineStyle": {"width": 1},
            "itemStyle": {"color": "#0066ff"},
        },
        {
            "name": "MA20",
            "type": "line",
            "data": ma20,
            "lineStyle": {"width": 1},
            "itemStyle": {"color": "#cc00cc"},
        },
        {
            "name": "成交量",
            "type": "bar",
            "data": volumes,
            "yAxisIndex": 1,
        },
    ]

    # 最新指标标注
    latest = closes[-1] if closes else 0
    annotations = []
    if ma5 and ma5[-1] is not None:
        annotations.append({"name": "MA5", "value": round(ma5[-1], 2)})
    if ma20 and ma20[-1] is not None:
        annotations.append({"name": "MA20", "value": round(ma20[-1], 2)})

    return {
        "type": "candlestick",
        "title": f"{stock_name}（{ticker}）K线图",
        "x_axis": dates,
        "series": series,
        "annotations": annotations,
        "indicators": {
            "最新收盘": round(latest, 2) if latest else None,
            "MA5": round(ma5[-1], 2) if ma5 and ma5[-1] is not None else None,
            "MA20": round(ma20[-1], 2) if ma20 and ma20[-1] is not None else None,
        },
    }


def _build_prediction_chart(prediction: dict, ticker: str, stock_name: str) -> dict:
    """构建价格预测图。"""
    forecasts = prediction.get("forecasts", [])
    current_price = prediction.get("current_price", 0)
    direction = prediction.get("direction", "")
    direction_score = prediction.get("direction_score", 0)
    support = prediction.get("support_level")
    resistance = prediction.get("resistance_level")

    dates = []
    medians = []
    lows = []
    highs = []

    for f in forecasts:
        h = f.get("horizon_days", 0)
        dates.append(f"T+{h}")
        medians.append(f.get("median_price"))
        lows.append(f.get("low_price"))
        highs.append(f.get("high_price"))

    series = [
        {
            "name": "中位预测",
            "type": "line",
            "data": medians,
            "lineStyle": {"width": 2, "color": "#6366f1"},
            "itemStyle": {"color": "#6366f1"},
        },
        {
            "name": "置信上界",
            "type": "line",
            "data": highs,
            "lineStyle": {"width": 1, "type": "dashed", "color": "#10b981"},
            "itemStyle": {"color": "#10b981"},
        },
        {
            "name": "置信下界",
            "type": "line",
            "data": lows,
            "lineStyle": {"width": 1, "type": "dashed", "color": "#e6545a"},
            "itemStyle": {"color": "#e6545a"},
        },
    ]

    annotations = []
    if support is not None:
        annotations.append({"name": "支撑位", "value": support})
    if resistance is not None:
        annotations.append({"name": "压力位", "value": resistance})

    return {
        "type": "prediction",
        "title": f"{stock_name}（{ticker}）价格预测",
        "x_axis": dates,
        "series": series,
        "annotations": annotations,
        "indicators": {
            "当前价格": current_price,
            "方向": direction,
            "上涨概率": direction_score,
            "支撑位": support,
            "压力位": resistance,
        },
    }


def _build_technical_chart(hist_data: list, tech: dict, ticker: str, stock_name: str) -> dict:
    """构建技术指标图（多面板：价格 + MACD + RSI）。"""
    dates = [d.get("date", "") for d in hist_data]
    closes = [float(d.get("close", 0)) for d in hist_data]

    # MACD 计算（用 features 的逻辑简化）
    macd_bar = _compute_macd_bar(closes)

    series = [
        {
            "name": "收盘价",
            "type": "line",
            "data": closes,
            "lineStyle": {"width": 1.5},
        },
        {
            "name": "MACD柱",
            "type": "bar",
            "data": macd_bar,
            "yAxisIndex": 1,
        },
    ]

    annotations = []
    if tech.get("rsi_14") is not None:
        annotations.append({"name": "RSI", "value": tech["rsi_14"]})
    if tech.get("macd_relation"):
        annotations.append({"name": "MACD", "value": tech["macd_relation"]})

    return {
        "type": "technical",
        "title": f"{stock_name}（{ticker}）技术指标",
        "x_axis": dates,
        "series": series,
        "annotations": annotations,
        "indicators": {
            "趋势": tech.get("trend_state"),
            "RSI": tech.get("rsi_14"),
            "MACD": tech.get("macd_relation"),
            "KDJ-K": tech.get("kdj_k"),
            "布林上轨": tech.get("boll_upper"),
            "布林下轨": tech.get("boll_lower"),
        },
    }


def _moving_average(data: list, window: int) -> list:
    """简单移动平均。"""
    result = [None] * len(data)
    for i in range(window - 1, len(data)):
        result[i] = round(sum(data[i - window + 1:i + 1]) / window, 2)
    return result


def _compute_macd_bar(closes: list) -> list:
    """简化 MACD 柱状图计算。"""
    if len(closes) < 26:
        return [0] * len(closes)
    import pandas as pd
    s = pd.Series(closes)
    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    bar = ((dif - dea) * 2).tolist()
    return [round(v, 3) for v in bar]
