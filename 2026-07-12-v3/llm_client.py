"""
Gemini / Gemma (Google AI Studio) LLM 接入层。
API Key 仅从环境变量 GEMINI_API_KEY 读取（不硬编码，避免泄露）。
模型默认使用 Gemma 4 31B（gemma-4-31b-it），可通过 GEMINI_MODEL 覆盖。
若 Key 为空或调用失败，自动降级为关键词启发式解析。
"""
import os
import json
import re

# 仅从环境变量读取，绝不硬编码密钥
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Gemma 4 31B：通过 Gemini API 的 generateContent 端点调用
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemma-4-31b-it")

SYSTEM_PROMPT = """你是一个股票信息查询助手的意图解析器。
根据用户消息，提取结构化查询参数，并以 JSON 返回，不要输出多余文字。
字段说明：
- code: 股票代码（6位数字），若消息中只有名称则留空字符串
- name: 股票名称（如「贵州茅台」），若只有代码则留空
- intent: 数组，可包含 "profile"（上市详情）、"history"（历史日线行情）、"intraday"（盘中/分时行情）
- date: 日期 YYYY-MM-DD（用于 history/intraday），无则空
- start_date / end_date: history 的起止日期 YYYY-MM-DD，无则空
- time: 盘中具体时间 HH:MM（用于 intraday），无则空

示例：
用户：「查询 贵州茅台(600519) 2026年7月10日14:00 的股票信息」
返回：{"code":"600519","name":"贵州茅台","intent":["profile","intraday"],"date":"2026-07-10","start_date":"","end_date":"","time":"14:00"}

只返回 JSON。
"""

SUMMARY_PROMPT = """你是一个对话标题生成器。请用不超过 20 个汉字，概括下面这条用户消息的核心意图，作为会话标题。只返回标题文本，不要引号、不要解释。"""


def _call_gemini(prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0):
    """调用 Gemini/Gemma generateContent 端点，返回文本。无 key 或失败时抛异常。"""
    import requests
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未设置")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
           f"?key={GEMINI_API_KEY}")
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
    }
    r = requests.post(url, json=payload, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def parse_intent(message):
    """返回结构化意图 dict。优先用 LLM，无 key 或失败时降级为关键词解析。"""
    if GEMINI_API_KEY:
        try:
            raw = _call_gemini(message)
            parsed = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            parsed.setdefault("code", "")
            parsed.setdefault("name", "")
            parsed.setdefault("intent", [])
            parsed.setdefault("date", "")
            parsed.setdefault("start_date", "")
            parsed.setdefault("end_date", "")
            parsed.setdefault("time", "")
            if isinstance(parsed["intent"], str):
                parsed["intent"] = [parsed["intent"]]
            return parsed
        except Exception as e:
            print(f"[llm] Gemma 解析失败，降级关键词：{e}")
    return _keyword_parse(message)


def summarize_title(message):
    """用 LLM 生成会话标题（首条用户消息摘要）；失败则返回截断的原消息。"""
    if GEMINI_API_KEY:
        try:
            text = _call_gemini(message, system_prompt=SUMMARY_PROMPT, temperature=0.3)
            title = text.strip().strip('"').strip("'")
            if title:
                return title[:30]
        except Exception as e:
            print(f"[llm] 标题生成失败，降级原消息：{e}")
    return message[:20]


def _keyword_parse(message):
    """无 LLM 时的关键词启发式解析（与 v2 行为一致）。"""
    code_m = re.search(r"\b(\d{6})\b", message)
    code = code_m.group(1) if code_m else ""
    intent = []
    if any(k in message for k in ["上市", "板块", "主营", "行业", "上市日期", "资料"]):
        intent.append("profile")
    if any(k in message for k in ["盘中", "分时", "14:", "15:", "09:", "10:", "11:", "13:", "实时", "当时"]):
        intent.append("intraday")
    if any(k in message for k in ["行情", "价格", "开盘", "收盘", "最高", "最低", "历史", "K线", "成交量"]):
        intent.append("history")
    if not intent:
        intent = ["profile", "history"]
    # 仅匹配带明确分隔符的日期，避免误吞 6 位股票代码（如 600519）
    dm = re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", message)
    if not dm:
        dm = re.findall(r"(\d{4})-(\d{2})-(\d{2})", message)
    date = ""
    start_date = end_date = ""
    if dm:
        d = f"{dm[0][0]}-{int(dm[0][1]):02d}-{int(dm[0][2]):02d}"
        date = d
        if len(dm) >= 2:
            start_date = d
            end_date = f"{dm[1][0]}-{int(dm[1][1]):02d}-{int(dm[1][2]):02d}"
    tm = re.search(r"(\d{1,2}):(\d{2})", message)
    time = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else ""
    return {"code": code, "name": "", "intent": intent,
            "date": date, "start_date": start_date, "end_date": end_date, "time": time}
