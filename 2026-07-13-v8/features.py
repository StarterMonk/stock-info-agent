"""
v7 特征工程：常用技术指标向量化计算（零第三方指标库依赖，纯 pandas）。
输出两用：全量指标矩阵（回测/训练） + 最新快照（工具返回，支撑/压力位/多空状态）。
"""
import pandas as pd
import numpy as np


def indicator_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """输入含 open_price/high_price/low_price/close_price/volume_hands 的日线 → 追加指标列。"""
    df = frame.copy()
    close, high, low = df["close_price"], df["high_price"], df["low_price"]

    for window in (5, 10, 20, 60):
        df[f"ma_{window}"] = close.rolling(window).mean()

    df["ema_12"] = close.ewm(span=12, adjust=False).mean()
    df["ema_26"] = close.ewm(span=26, adjust=False).mean()
    df["macd_dif"] = df["ema_12"] - df["ema_26"]
    df["macd_dea"] = df["macd_dif"].ewm(span=9, adjust=False).mean()
    df["macd_bar"] = (df["macd_dif"] - df["macd_dea"]) * 2

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    relative_strength = gain / loss.replace(0, np.nan)
    df["rsi_14"] = (100 - 100 / (1 + relative_strength)).fillna(50)

    low_9 = low.rolling(9).min()
    high_9 = high.rolling(9).max()
    rsv = ((close - low_9) / (high_9 - low_9).replace(0, np.nan) * 100).fillna(50)
    df["kdj_k"] = rsv.ewm(com=2, adjust=False).mean()
    df["kdj_d"] = df["kdj_k"].ewm(com=2, adjust=False).mean()
    df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]

    mid_20 = close.rolling(20).mean()
    std_20 = close.rolling(20).std()
    df["boll_mid"] = mid_20
    df["boll_upper"] = mid_20 + 2 * std_20
    df["boll_lower"] = mid_20 - 2 * std_20

    previous_close = close.shift(1)
    true_range = pd.concat([
        high - low,
        (high - previous_close).abs(),
        (low - previous_close).abs(),
    ], axis=1).max(axis=1)
    df["atr_14"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()

    df["log_return"] = np.log(close / close.shift(1))
    df["momentum_5d"] = close / close.shift(5) - 1
    df["momentum_20d"] = close / close.shift(20) - 1
    df["volume_ratio"] = df["volume_hands"] / df["volume_hands"].rolling(20).mean()
    return df


def technical_snapshot(frame: pd.DataFrame) -> dict:
    """最新指标快照：趋势状态、均线、MACD/RSI/KDJ/BOLL/ATR、量比、支撑压力位。"""
    df = indicator_frame(frame)
    if df is None or len(df) < 60:
        return {}
    last = df.iloc[-1]
    close_price = float(last["close_price"])
    ma20, ma60 = float(last["ma_20"]), float(last["ma_60"])
    ma20_previous = float(df["ma_20"].iloc[-6])

    if close_price > ma20 > ma60 and ma20 > ma20_previous:
        trend_state = "多头"
    elif close_price < ma20 < ma60 and ma20 < ma20_previous:
        trend_state = "空头"
    else:
        trend_state = "震荡"

    recent_low = float(df["low_price"].iloc[-60:].min())
    recent_high = float(df["high_price"].iloc[-60:].max())
    overbought = float(last["rsi_14"]) > 70
    oversold = float(last["rsi_14"]) < 30
    macd_relation = "金叉" if float(last["macd_dif"]) > float(last["macd_dea"]) else "死叉"
    return {
        "trend_state": trend_state,
        "close_price": round(close_price, 2),
        "ma_5": round(float(last["ma_5"]), 2),
        "ma_20": round(ma20, 2),
        "ma_60": round(ma60, 2),
        "macd_dif": round(float(last["macd_dif"]), 3),
        "macd_dea": round(float(last["macd_dea"]), 3),
        "macd_bar": round(float(last["macd_bar"]), 3),
        "macd_relation": macd_relation,
        "rsi_14": round(float(last["rsi_14"]), 1),
        "overbought": overbought,
        "oversold": oversold,
        "kdj_k": round(float(last["kdj_k"]), 1),
        "kdj_d": round(float(last["kdj_d"]), 1),
        "kdj_j": round(float(last["kdj_j"]), 1),
        "boll_upper": round(float(last["boll_upper"]), 2),
        "boll_lower": round(float(last["boll_lower"]), 2),
        "atr_14": round(float(last["atr_14"]), 2),
        "volume_ratio": round(float(last["volume_ratio"]), 2),
        "momentum_5d": round(float(last["momentum_5d"]), 4),
        "momentum_20d": round(float(last["momentum_20d"]), 4),
        "support_level": round(recent_low, 2),
        "resistance_level": round(recent_high, 2),
    }