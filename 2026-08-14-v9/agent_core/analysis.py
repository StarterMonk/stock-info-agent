"""
v8 分析引擎：可插拔算法池（MA / MA5+线性回归 / EMA / BOLL / SARIMA）。
输出统一结构：OHLC 点 + 叠加线 + 结论，供前端图表工作台直接渲染。
"""
import re
import math
import pandas as pd
import numpy as np

import data_layer
import features
import models

ALGORITHMS = [
    {"key": "ma", "label": "MA 移动平均线", "desc": "MA5 / MA20 双均线，观察金叉死叉与趋势支撑。", "group": "均线"},
    {"key": "ma_reg", "label": "MA5 + 线性回归", "desc": "均线叠加最小二乘趋势线，量化方向与斜率。", "group": "趋势"},
    {"key": "ema", "label": "EMA 指数均线", "desc": "EMA12 / EMA26，近期价格权重更高、更灵敏。", "group": "均线"},
    {"key": "boll", "label": "BOLL 布林带", "desc": "20 日布林带 ±2σ，判断超买超卖与波动区间。", "group": "波动"},
    {"key": "sarima", "label": "SARIMA 预测", "desc": "SARIMA(1,1,1) + EMA 基线，未来 10 日置信带。", "group": "预测"},
]

COLORS = {"a": "#6366f1", "b": "#f59e0b", "c": "#10b981", "d": "#ef4444", "up": "#e6545a", "down": "#2e9e6b"}


def _ohlc_points(df: pd.DataFrame) -> list:
    return [
        {"date": str(r["trade_date"])[:10],
         "open": round(float(r["open_price"]), 2),
         "high": round(float(r["high_price"]), 2),
         "low": round(float(r["low_price"]), 2),
         "close": round(float(r["close_price"]), 2)}
        for _, r in df.iterrows()
    ]


def _series(df: pd.DataFrame, column: str, label: str, color: str) -> dict:
    points = []
    for d, v in zip(df["trade_date"].astype(str).str[:10], df[column]):
        if pd.isna(v):
            continue
        points.append({"date": d, "value": round(float(v), 2)})
    return {"key": column, "label": label, "color": color, "points": points}


def _trend_verdict(df: pd.DataFrame, algorithm: str) -> str:
    last = df.iloc[-1]
    close, ma5, ma20 = last["close_price"], last["ma_5"], last["ma_20"]
    prev = df.iloc[-2]
    if algorithm == "ma":
        if prev["ma_5"] <= prev["ma_20"] and ma5 > ma20:
            return f"MA5 今日上穿 MA20（金叉），短线动量转强 → 偏多关注。"
        if prev["ma_5"] >= prev["ma_20"] and ma5 < ma20:
            return f"MA5 今日下穿 MA20（死叉），短线动量转弱 → 偏空警惕。"
        return f"MA5({ma5:.2f}) {'>' if ma5 > ma20 else '<'} MA20({ma20:.2f})，均线{('多头' if ma5 > ma20 else '空头')}排列、趋势延续。"
    if algorithm == "ma_reg":
        return f"收盘 {close:.2f}，MA5 {ma5:.2f}（{'多头' if ma5 > ma20 else '空头'}排列）。"
    if algorithm == "ema":
        cross = "金叉" if last["ema_12"] > last["ema_26"] else "死叉"
        return f"EMA12 {last['ema_12']:.2f} {'>' if last['ema_12'] > last['ema_26'] else '<'} EMA26 {last['ema_26']:.2f}（{cross}）。"
    if algorithm == "boll":
        upper, lower, mid = last["boll_upper"], last["boll_lower"], last["boll_mid"]
        pos = "触及上轨（超买区）" if close >= upper else ("触及下轨（超卖区）" if close <= lower else "带内运行")
        return f"收盘 {close:.2f} {pos}；带幅 {(upper-lower):.2f}（{mid:.2f}±2σ）。"
    if algorithm == "sarima":
        return f"模型方向与置信带见上表；基于历史统计推断，不构成投资建议。"
    return ""


def run_analysis(code: str, algorithm: str) -> dict:
    if not re.fullmatch(r"\d{6}", code or ""):
        return {"code": code, "error": "股票代码需为 6 位数字"}
    if algorithm not in {a["key"] for a in ALGORITHMS}:
        return {"code": code, "error": f"未知算法 {algorithm}"}

    data_layer.initialize_database()
    frame = data_layer.load_history(code, years=3)
    if frame is None or len(frame) < 120:
        return {"code": code, "error": "历史数据不足（需至少 120 个交易日，已尝试自动回填）"}

    df = features.indicator_frame(frame).tail(120).reset_index(drop=True)
    points = _ohlc_points(df)
    overlays, latest = [], {}
    verdict = _trend_verdict(df, algorithm)

    if algorithm == "ma":
        overlays = [_series(df, "ma_5", "MA5", COLORS["a"]),
                    _series(df, "ma_20", "MA20", COLORS["b"])]
        latest = {"均线状态": "多头排列" if df["ma_5"].iloc[-1] > df["ma_20"].iloc[-1] else "空头排列",
                  "MA5": round(float(df["ma_5"].iloc[-1]), 2),
                  "MA20": round(float(df["ma_20"].iloc[-1]), 2)}

    elif algorithm == "ma_reg":
        ma5 = _series(df, "ma_5", "MA5", COLORS["a"])
        close = df["close_price"].astype(float).tail(60).reset_index(drop=True)
        x = np.arange(len(close))
        slope, intercept = np.polyfit(x, close.values if hasattr(close, "values") else close, 1)
        end_idx = len(close) - 1
        reg_line = {"key": "linreg", "label": "线性回归", "color": COLORS["c"], "points": [
            {"date": df["trade_date"].astype(str).str[:10].iloc[i],
             "value": round(float(slope * i + intercept), 2)}
            for i in range(len(close)) if i % 5 == 0]}
        overlays = [ma5, reg_line]
        slope_pct = slope / close.iloc[0] * 100 if close.iloc[0] else 0
        latest = {"近 60 日斜率": f"{slope_pct:+.2f}% /日",
                  "方向": "上行趋势" if slope > 0 else "下行趋势"}

    elif algorithm == "ema":
        overlays = [_series(df, "ema_12", "EMA12", COLORS["a"]),
                    _series(df, "ema_26", "EMA26", COLORS["b"])]
        latest = {"EMA12": round(float(df["ema_12"].iloc[-1]), 2),
                  "EMA26": round(float(df["ema_26"].iloc[-1]), 2),
                  "MACD 柱": round(float(df["macd_bar"].iloc[-1]), 3)}

    elif algorithm == "boll":
        overlays = [_series(df, "boll_upper", "上轨", COLORS["c"]),
                    _series(df, "boll_mid", "中轨", COLORS["b"]),
                    _series(df, "boll_lower", "下轨", COLORS["c"])]
        latest = {"收盘": round(float(df["close_price"].iloc[-1]), 2),
                  "上轨": round(float(df["boll_upper"].iloc[-1]), 2),
                  "中轨": round(float(df["boll_mid"].iloc[-1]), 2),
                  "下轨": round(float(df["boll_lower"].iloc[-1]), 2)}

    elif algorithm == "sarima":
        forecast = models.price_forecast(code, horizons=(10,))
        if forecast.get("error"):
            return {"code": code, "error": forecast["error"]}
        first = forecast["forecasts"][0]
        last_date = df["trade_date"].iloc[-1]
        target_date = pd.Timestamp(last_date) + pd.Timedelta(days=14)
        base = df["close_price"].iloc[-1]
        overlays = [
            {"key": "fc_med", "label": "中位价", "color": COLORS["a"], "points": [
                {"date": str(last_date)[:10], "value": round(float(base), 2)},
                {"date": str(target_date)[:10], "value": round(float(first["median_price"]), 2)}]},
            {"key": "fc_low", "label": "置信下沿", "color": COLORS["c"], "points": [
                {"date": str(last_date)[:10], "value": round(float(base), 2)},
                {"date": str(target_date)[:10], "value": round(float(first["low_price"]), 2)}]},
            {"key": "fc_high", "label": "置信上沿", "color": COLORS["b"], "points": [
                {"date": str(last_date)[:10], "value": round(float(base), 2)},
                {"date": str(target_date)[:10], "value": round(float(first["high_price"]), 2)}]},
        ]
        latest = {"方向": forecast["direction"], "概率": forecast["direction_score"],
                  "支撑": forecast["support_level"], "压力": forecast["resistance_level"],
                  "10 日中位价": first["median_price"]}

    result = {
        "code": code,
        "algorithm": algorithm,
        "algorithm_label": {a["key"]: a["label"] for a in ALGORITHMS}[algorithm],
        "points": points,
        "overlays": overlays,
        "latest": latest,
        "verdict": verdict,
        "ts": str(df["trade_date"].iloc[-1])[:10],
        "disclaimer": "分析基于历史数据统计推断，不构成投资建议。",
    }
    return result