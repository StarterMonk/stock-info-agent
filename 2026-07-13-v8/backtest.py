"""
v7 回测门禁：walk-forward 滚动验证预测质量。

标准（GATE）：
- 方向准确率 >= 55%（GATE_MIN_ACCURACY）
- 且至少比随机游走基线高 5 个百分点（GATE_EDGE_OVER_BASELINE）
满足才在报告中标注「预测可信」；否则提示历史动量不足，谨慎采纳。
"""
import logging

import data_layer

logger = logging.getLogger(__name__)

GATE_MIN_ACCURACY = 0.55
GATE_EDGE_OVER_BASELINE = 0.05


def _walk_forward_pairs(close, train_days=400, test_days=20):
    """滚动窗口：每个测试窗口用前 train_days 训练 EMA 漂移信号，比较窗口末方向。"""
    pairs = []
    start = train_days
    while start + test_days <= len(close):
        train = close.iloc[start - train_days: start]
        test = close.iloc[start: start + test_days]
        ema = float(train.ewm(span=20, adjust=False).mean().iloc[-1])
        drift = float(train.iloc[-1]) / ema - 1.0
        signal = 1 if drift > 1e-6 else (-1 if drift < -1e-6 else 0)
        realized = 1 if float(test.iloc[-1]) > float(train.iloc[-1]) else -1
        pairs.append((signal, realized))
        start += test_days
    return pairs


def rolling_accuracy(code: str) -> dict:
    """对单只股票做 walk-forward 方向准确性评估，返回门禁结果。"""
    frame = data_layer.load_history(code, years=3)
    if frame is None:
        return {"code": code, "valid": False, "reason": "无本地历史数据"}
    close = frame["close_price"].astype(float).reset_index(drop=True)
    pairs = _walk_forward_pairs(close)
    if len(pairs) < 3:
        return {"code": code, "valid": False, "reason": "历史长度不足，无法回测"}
    hits = sum(1 for signal, realized in pairs if signal == realized)
    accuracy = hits / len(pairs)
    baseline_hits = sum(1 for _, realized in pairs if realized == 1)
    baseline_accuracy = baseline_hits / len(pairs)
    passed = accuracy >= GATE_MIN_ACCURACY and accuracy >= baseline_accuracy + GATE_EDGE
    return {
        "code": code,
        "valid": True,
        "windows_tested": len(pairs),
        "direction_accuracy": round(accuracy, 4),
        "random_walk_accuracy": round(baseline_accuracy, 4),
        "gate_passed": passed,
    }