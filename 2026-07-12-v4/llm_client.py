"""
Gemini / Gemma (Google AI Studio) LLM 接入层 —— v4 多轮 + 工具调用版。

特性：
- API Key 仅从环境变量 GEMINI_API_KEY 读取（不硬编码）。
- 模型默认 gemma-4-31b-it，可用 GEMINI_MODEL 覆盖。
- 支持「多轮 contents」：调用方传入完整对话历史（含 functionCall / functionResponse），
  实现 stateful 多轮对话与工具调用闭环。
- 支持 function calling：传入 tools 声明，返回候选内容（可能含 functionCall）。
- 无 key 或失败时，提供关键词降级（仅用于意图解析，不用于工具调用闭环）。

参考 Google Generative Language API：generateContent 端点 + tools/functionCalling。
"""
import os
import json
import re

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemma-4-31b-it")

SYSTEM_PROMPT = """你是一个专业的 A 股股票信息助手 Agent。
你可以调用一组工具来获取目标股票的各类信息（公司资料、历史行情、盘中分时、财务报表、分红、资金流向、财务指标、业绩报告等）。
工作流程：
1. 先理解用户意图，必要时调用工具获取真实数据；
2. 工具返回后，基于真实数据用中文清晰作答，并标注数据来源；
3. 若工具不可用或返回错误，如实说明，并尽量给出替代建议；
4. 结合对话历史与长期记忆，保持上下文连贯，主动关联用户此前关注的股票。
只输出面向用户的最终回答，不要输出内部工具调用细节。"""

SUMMARY_PROMPT = """你是一个对话标题生成器。请用不超过 20 个汉字，概括下面这条用户消息的核心意图，作为会话标题。只返回标题文本，不要引号、不要解释。"""


def _call_gemini(prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0, tools=None, contents=None):
    """调用 generateContent。contents 为完整多轮内容；tools 为 functionDeclaration 列表。"""
    import requests
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未设置")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
           f"?key={GEMINI_API_KEY}")
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents if contents is not None else [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    if tools:
        payload["tools"] = [{"functionDeclarations": tools}]
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    return r.json()


def generate(contents, tools=None, temperature=0.3, system_prompt=None):
    """多轮生成。返回原始 candidates[0].content（含 parts，可能含 functionCall）。无 key 抛异常。"""
    data = _call_gemini("", contents=contents, temperature=temperature, tools=tools,
                        system_prompt=system_prompt or SYSTEM_PROMPT)
    return data["candidates"][0]["content"]


def parse_intent(message):
    """兼容旧接口：单轮意图解析（优先 LLM，失败降级关键词）。"""
    if GEMINI_API_KEY:
        try:
            raw = _call_gemini(message)
            parsed = json.loads(re.search(r"\{.*\}", raw["candidates"][0]["content"]["parts"][0]["text"], re.S).group(0))
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
    if GEMINI_API_KEY:
        try:
            text = _call_gemini(message, system_prompt=SUMMARY_PROMPT, temperature=0.3)["candidates"][0]["content"]["parts"][0]["text"]
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
