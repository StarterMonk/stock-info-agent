"""
简单分析方法（默认使用）：
1. 移动平均线外推（MA5/MA20/MA60）
2. EMA 指数移动平均外推
3. 布林带通道预测
4. 线性回归趋势外推
5. 季节分解（STL）
"""
import math
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def ma_forecast(close: pd.Series, horizons: list) -> dict:
    """移动平均线外推：基于 MA5/MA20/MA60 的加权预测。"""
    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    current = float(close.iloc[-1])

    # 权重：短期 MA 权重更高
    weighted_ma = (ma5 * 0.5 + ma20 * 0.3 + ma60 * 0.2)
    drift = (current / weighted_ma - 1.0) if weighted_ma > 0 else 0

    forecasts = {}
    for h in horizons:
        forecasts[h] = round(current * (1.0 + drift * h / 20.0), 2)
    return {"method": "MA均线外推", "forecasts": forecasts, "current_price": current}


def ema_forecast(close: pd.Series, horizons: list) -> dict:
    """指数移动平均外推：EMA12/EMA26 交叉信号。"""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    current = float(close.iloc[-1])

    # EMA 趋势方向
    ema12_val = float(ema12.iloc[-1])
    ema26_val = float(ema26.iloc[-1])
    trend = (ema12_val / ema26_val - 1.0) if ema26_val > 0 else 0

    forecasts = {}
    for h in horizons:
        forecasts[h] = round(current * (1.0 + trend * h / 20.0), 2)
    return {"method": "EMA指数外推", "forecasts": forecasts, "current_price": current}


def boll_forecast(close: pd.Series, horizons: list) -> dict:
    """布林带通道预测：中轨回归 + 波动率通道。"""
    mid = close.rolling(20).mean().iloc[-1]
    std = close.rolling(20).std().iloc[-1]
    current = float(close.iloc[-1])

    # 中轨回归力
    reversion = (mid / current - 1.0) if current > 0 else 0

    forecasts = {}
    for h in horizons:
        # 预测值向中轨回归，同时考虑波动
        predicted = current * (1.0 + reversion * min(h / 10.0, 1.0))
        forecasts[h] = round(predicted, 2)
    return {"method": "布林带回归", "forecasts": forecasts, "current_price": current}


def linear_regression_forecast(close: pd.Series, horizons: list) -> dict:
    """线性回归趋势外推：最小二乘拟合 + 外推。"""
    n = min(len(close), 60)
    y = close.tail(n).values.astype(float)
    x = np.arange(n).reshape(-1, 1)

    from sklearn.linear_model import LinearRegression
    model = LinearRegression()
    model.fit(x, y)

    current = float(close.iloc[-1])
    slope = model.coef_[0]
    intercept = model.intercept_

    forecasts = {}
    for h in horizons:
        pred = model.predict([[n + h - 1]])[0]
        # 限制单日变动不超过 5%
        max_change = current * 0.05 * h
        pred = max(current - max_change, min(current + max_change, pred))
        forecasts[h] = round(float(pred), 2)
    return {"method": "线性回归", "forecasts": forecasts, "current_price": current}


def seasonal_decomposition_forecast(close: pd.Series, horizons: list) -> dict:
    """季节分解外推：STL 分解趋势 + 季节性。"""
    try:
        from statsmodels.tsa.seasonal import STL
        stl = STL(close, period=5, robust=True)
        result = stl.fit()
        trend = result.trend
        seasonal = result.seasonal

        current = float(close.iloc[-1])
        trend_slope = float(trend.iloc[-1] - trend.iloc[-5]) / 5 if len(trend) > 5 else 0

        forecasts = {}
        for h in horizons:
            # 趋势 + 季节性
            trend_pred = current + trend_slope * h
            # 季节性周期（5天一周期）
            season_idx = h % 5
            season_val = float(seasonal.iloc[-(5 - season_idx) if season_idx else -5])
            pred = trend_pred + season_val * 0.5  # 季节性权重减半
            forecasts[h] = round(pred, 2)
        return {"method": "季节分解", "forecasts": forecasts, "current_price": current}
    except Exception as e:
        logger.warning("季节分解失败，回退线性回归: %s", e)
        return linear_regression_forecast(close, horizons)


def run_simple_methods(close: pd.Series, horizons: list) -> dict:
    """运行所有简单方法并返回集成结果。"""
    results = {}
    methods = [
        ("ma", ma_forecast),
        ("ema", ema_forecast),
        ("boll", boll_forecast),
        ("linear", linear_regression_forecast),
        ("seasonal", seasonal_decomposition_forecast),
    ]

    for name, fn in methods:
        try:
            results[name] = fn(close, horizons)
        except Exception as e:
            logger.warning("简单方法 %s 失败: %s", name, e)
            results[name] = None

    # 集成：中位数
    valid = [r for r in results.values() if r and "forecasts" in r]
    if not valid:
        return {"method": "simple_ensemble", "error": "所有简单方法均失败"}

    ensemble = {}
    for h in horizons:
        vals = [r["forecasts"][h] for r in valid if h in r["forecasts"]]
        if vals:
            ensemble[h] = round(float(np.median(vals)), 2)

    return {
        "method": "简单方法集成",
        "individual": {k: v for k, v in results.items() if v},
        "ensemble_forecasts": ensemble,
        "current_price": float(close.iloc[-1]),
        "methods_used": [r["method"] for r in valid],
    }
