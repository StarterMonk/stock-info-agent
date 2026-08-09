"""
v7 综合研判：多因子打分（0-10 分）+ LLM 自然语言研报。

权重：技术动量 40% + 估值水平 30% + 业绩趋势 15% + 统计共识 15%。
有 GEMINI_API_KEY / OPENROUTER_API_KEY 时由 LLM 生成研报叙事，否则模板兜底。
"""
import logging

import llm_client
import models

logger = logging.getLogger(__name__)


def _clamp(value, low, high):
    return max(low, min(high, value or 0.0))


def _valuation_score(rows) -> float:
    """简易估值打分：ROE/每股收益 方向性判断 → 0~10。"""
    score = 5.0
    for row in (rows or [])[-4:]:
        try:
            roe = float(row.get("净资产收益率(%)", row.get("加权净资产收益率(%)", 0)) or 0)
            earnings_per_share = float(row.get("每股收益", 0) or 0)
            if roe >= 15:
                score += 1.0
            if earnings_per_share <= 0:
                score -= 2.0
        except (TypeError, ValueError, KeyError):
            continue
    return _clamp(score, 0, 10)


def _earnings_score(rows) -> float:
    """业绩预告：净利润同比正增长加分，负增长减分 → 0~10。"""
    score = 5.0
    if not rows:
        return score
    latest = rows[-1]
    growth = latest.get("净利润同比", latest.get("净利润同比增长率", 0))
    try:
        result = float(growth or 0)
        score += 0.5 if result > 0 else -0.5
    except (TypeError, ValueError):
        pass
    return _clamp(score, 0, 10)


def multi_factor_score(code: str, forecast: dict, financial_rows=None, earnings_rows=None) -> dict:
    """按权重合成 0-10 综合分与维度分解。forecast 来自 models.price_forecast。"""
    tech_score = 5.0 + (forecast.get("direction_score", 0.5) - 0.5) * 10
    valuation_score = _valuation_score(financial_rows)
    earnings_score = _earnings_score(earnings_rows)
    consensus_score = 5.0 + (1 if forecast.get("direction") == "偏多"
                             else (-1 if forecast.get("direction") == "偏空" else 0))
    total = round(0.40 * tech_score + 0.30 * valuation_score
                  + 0.15 * earnings_score + 0.15 * consensus_score, 1)
    return {
        "total_score": _clamp(total, 0, 10),
        "breakdown": {
            "技术动量": round(tech_score, 1),
            "估值水平": round(valuation_score, 1),
            "业绩趋势": round(earnings_score, 1),
            "统计共识": round(consensus_score, 1),
        },
        "direction": forecast.get("direction", "中性"),
    }


def generate_report(code: str, forecast: dict, financial_rows=None, earnings_rows=None) -> dict:
    """生成研报：优先 LLM，失败/无 key 走模板。返回带 narrative 的多因子结果。"""
    factors = multi_factor_score(code, forecast, financial_rows, earnings_rows)
    trend = forecast.get("trend_summary", {})
    template = (
        f"技术面处于{trend.get('trend_state', '震荡')}状态，MACD"
        f"{trend.get('macd_relation', '不明')}；支撑位 {forecast.get('support_level')}，"
        f"压力位 {forecast.get('resistance_level')}；未来 5-20 交易日方向判断："
        f"{forecast.get('direction')}（上涨概率 {forecast.get('direction_score')}）。"
        f"多因子综合得分 {factors['total_score']} 分。风险：预测基于历史统计，不构成投资建议。")
    if llm_client.has_api_key():
        try:
            prompt = (
                "你是资深股票分析助手。请基于以下信号输出不超过 150 字的简体中文研判："
                f"技术面{trend.get('trend_state', '震荡')}，MACD{trend.get('macd_relation', '不明')}，"
                f"支撑{forecast.get('support_level')} / 压力{forecast.get('resistance_level')}，"
                f"上涨概率{forecast.get('direction_score')}，多因子得分{factors['total_score']}。"
                "格式：结论（一句）→ 依据（一句）→ 风险（一句），纯文本输出。")
            content = llm_client.generate([{"role": "user", "parts": [{"text": prompt}]}],
                                             system_prompt="你是股票研究助手，输出简洁严谨。")
            text = "".join(part.get("text", "") for part in content.get("parts", []))
            factors["narrative"] = text.strip() or template
            return factors
        except Exception as exc:
            logger.warning("LLM 研报失败，走模板兜底：%s", exc)
    factors["narrative"] = template
    return factors