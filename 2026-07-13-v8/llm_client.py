"""
v7-openrouter LLM 接入层：通过 OpenRouter API（OpenAI 兼容的 /chat/completions）驱动 Agent。

特性：
- API Key 从环境变量 OPENROUTER_API_KEY 读取（不硬编码）。
- 模型默认 nvidia/nemotron-3-ultra-550b-a55b:free，可用 OPENROUTER_MODEL 覆盖。
- 直接以 requests 调用 OpenRouter REST 接口，适配其传回的参数结构
  （choices[0].message.content / message.tool_calls[].function），
  不再依赖 langchain / langgraph。
- 支持 tool calling：请求体携带 OpenAI 格式 tools，返回结构化 tool_calls。
- 无 key 或调用失败时降级为关键词模式（仅意图解析）。
"""
import os
import json
import re
import logging

import requests

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")

SYSTEM_PROMPT = """你是一个专业的 A 股股票信息助手 Agent。
你可以调用一组工具来获取目标股票的各类信息（公司资料、历史行情、盘中分时、财务报表、分红、资金流向、财务指标、技术指标、业绩报告、价格预测等）。
工作流程：
1. 先理解用户意图，必要时调用工具获取真实数据；
2. 工具返回后，基于真实数据用中文清晰作答，并标注数据来源；
3. 若工具不可用或返回错误，如实说明，并尽量给出替代建议；
4. 结合对话历史与长期记忆，保持上下文连贯，主动关联用户此前关注的股票。
5. 涉及价格预测（get_price_prediction）时，务必在回答末尾注明「预测基于历史统计，不构成投资建议」。
注意：get_technical_indicators 是技术面指标（MA/MACD/RSI 等），get_indicators 是财务估值指标（每股收益等），不要混淆。
只输出面向用户的最终回答，不要输出内部工具调用细节。"""

SUMMARY_PROMPT = """你是一个对话标题生成器。请用不超过 20 个汉字概括下面这条用户消息的核心意图，作为会话标题。只返回标题文本，不要引号、不要解释。"""


def has_api_key() -> bool:
    """供 reporter 等模块判断是否可启用 LLM 研报。"""
    return bool(OPENROUTER_API_KEY)


# ---------------------------------------------------------------------------
# OpenRouter Chat Completions
# ---------------------------------------------------------------------------
def _api_path(endpoint: str) -> str:
    return f"{OPENROUTER_BASE_URL.rstrip('/')}/{endpoint}"


def chat(system_prompt: str, messages: list, tools: list = None,
         temperature: float = 0.3, max_tokens: int = 2048, timeout: int = 90) -> dict:
    """OpenRouter 对话补全（非流式）。

    messages: [{"role": "user"|"assistant"|"tool", "content": str, ...}]
    tools:   OpenAI function 声明列表（可选）。
    返回: {"content": str, "tool_calls": [{"id","name","arguments": dict}], "finish_reason": str}

    适配说明（针对 OpenRouter 返回参数结构）：
    - 正文在 response["choices"][0]["message"]["content"]
    - 工具调用在 ["choices"][0]["message"]["tool_calls"][i]["function"]["name"/"arguments"]
    - arguments 为 JSON 字符串，统一在此解析为 dict，供上层直接使用。
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY 未设置，无法调用 OpenRouter")
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": ([{"role": "system", "content": system_prompt}] if system_prompt else []) + messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    response = requests.post(_api_path("chat/completions"), json=payload,
                             headers=headers, timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter 请求失败 HTTP {response.status_code}: {response.text[:300]}")
    data = response.json()
    try:
        message = data["choices"][0]["message"]
        finish_reason = data["choices"][0].get("finish_reason", "")
        content = message.get("content") or ""
        raw_calls = message.get("tool_calls") or []
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"OpenRouter 返回结构异常：{exc}；原文前 300 字符：{str(data)[:300]}") from exc

    tool_calls = []
    for call in raw_calls:
        function = call.get("function", {})
        try:
            arguments = json.loads(function.get("arguments", "{}"))
        except (ValueError, TypeError):
            arguments = {}
        if isinstance(arguments, dict):
            tool_calls.append({
                "id": call.get("id", ""),
                "name": function.get("name", ""),
                "arguments": arguments,
            })
    return {"content": content, "tool_calls": tool_calls, "finish_reason": finish_reason}


def generate(contents: list, temperature: float = 0.3,
             system_prompt: str = None, max_tokens: int = 1024) -> dict:
    """兼容 v7 reporter 的生成接口。

    contents: [{"role": "user", "parts": [{"text": "..."}]}]
    返回: {"parts": [{"text": "..."}]}（兼容旧调用方）。
    """
    messages = []
    for item in contents or []:
        text = "".join(part.get("text", "") for part in item.get("parts", []))
        role = "assistant" if item.get("role") == "model" else "user"
        messages.append({"role": role, "content": text})
    result = chat(system_prompt or SYSTEM_PROMPT, messages,
                  temperature=temperature, max_tokens=max_tokens)
    return {"parts": [{"text": result["content"]}]}


# ---------------------------------------------------------------------------
# 意图解析 / 标题生成（LLM 优先，失败降级关键词）
# ---------------------------------------------------------------------------
def _parse_int_json(text: str):
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except ValueError:
        return None


def parse_intent(message: str) -> dict:
    """解析用户消息 → {code, name, intent[], date, start_date, end_date, time}。"""
    if OPENROUTER_API_KEY:
        try:
            result = chat(
                system_prompt=(
                    "将用户消息解析为 JSON：{code, name, intent[], date, start_date, end_date, time}。"
                    "intent 取值：profile/history/intraday/prediction/technical_indicators/indicators/"
                    "key_metrics/financials/dividend/forecast。股票为 6 位数字代码，名称用中文。"),
                messages=[{"role": "user", "content": message}],
                temperature=0.0, max_tokens=256)
            parsed = _parse_int_json(result["content"])
            if parsed and isinstance(parsed, dict):
                for key in ("code", "name", "date", "start_date", "end_date", "time"):
                    parsed.setdefault(key, "")
                parsed.setdefault("intent", [])
                if isinstance(parsed["intent"], str):
                    parsed["intent"] = [parsed["intent"]]
                return parsed
        except Exception as exc:
            logger.warning("[llm] OpenRouter 意图解析失败，降级关键词：%s", exc)
    return _keyword_parse(message)


_NAME_STOP = set("的了吗呢吧啊呀在是和与及或查询最近一个现在今天明天多少什么怎么样怎么请帮我我想要看看分析告诉帮讲讲有没有涨跌年走势如何")
_NAME_SUFFIX = ("行情", "走势", "价格", "预测", "业绩", "报告", "股价", "情况",
                "数据", "问题", "分析", "业务", "后市", "未来", "今年", "如何",
                "现在", "目前", "时候",
                "涨价", "跌价", "涨停", "跌停", "上涨", "下跌")
_HAN_RE = re.compile(r"[\u4e00-\u9fa5]+")


def _extract_name(message: str) -> str:
    """启发式提取股票名称：枚举 2-6 字窗口，剔除含虚词/以行情类后缀结尾的片段，取最长。"""
    text = message or ""
    cands = []
    for i in range(len(text)):
        for size in (2, 3, 4, 5, 6):
            if i + size > len(text):
                continue
            run = text[i:i + size]
            if not _HAN_RE.fullmatch(run):
                continue
            if any(ch in _NAME_STOP for ch in run):
                continue
            if run.endswith(_NAME_SUFFIX):
                continue
            cands.append(run)
    if not cands:
        return ""
    cands.sort(key=lambda c: (-len(c), text.index(c)))
    return cands[0]
    runs = []
    for m in re.finditer(r"(?=([\u4e00-\u9fa5]{2,6}))", message or ""):
        run = m.group(1)
        if not any(ch in _NAME_STOP for ch in run):
            runs.append(run)
    return max(runs, key=len) if runs else ""


def _keyword_parse(message: str) -> dict:
    """无 LLM 时的关键词启发式解析（同 v7 关键词模式）。"""
    code_match = re.search(r"\b(\d{6})\b", message)
    code = code_match.group(1) if code_match else ""
    intent = []
    if any(k in message for k in ["上市", "板块", "主营", "行业", "上市日期", "资料"]):
        intent.append("profile")
    if any(k in message for k in ["盘中", "分时", "14:", "15:", "09:", "10:", "11:", "13:", "实时", "当时"]):
        intent.append("intraday")
    if any(k in message for k in ["行情", "价格", "开盘", "收盘", "最高", "最低", "历史", "K线", "成交量"]):
        intent.append("history")
    if any(k in message for k in ["预测", "目标价", "上涨概率", "走势", "未来涨", "后市"]):
        intent.append("prediction")
    if any(k in message for k in ["技术指标", "MACD", "RSI", "KDJ", "金叉", "死叉", "趋势"]):
        intent.append("technical_indicators")
    if not intent:
        intent = ["profile", "history"]
    dm = re.findall(r"(\d{4})年(\d{1,2})月(\d{1,2})日", message)
    if not dm:
        dm = re.findall(r"(\d{4})-(\d{2})-(\d{2})", message)
    date = ""
    start_date = end_date = ""
    if dm:
        day = f"{dm[0][0]}-{int(dm[0][1]):02d}-{int(dm[0][2]):02d}"
        date = day
        if len(dm) >= 2:
            start_date = day
            end_date = f"{dm[1][0]}-{int(dm[1][1]):02d}-{int(dm[1][2]):02d}"
    tm = re.search(r"(\d{1,2}):(\d{2})", message)
    time = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else ""
    name = _extract_name(message)
    return {"code": code, "name": name, "intent": intent,
            "date": date, "start_date": start_date, "end_date": end_date, "time": time}


def summarize_title(message: str) -> str:
    """对话标题生成；失败降级消息前 20 字符。"""
    if OPENROUTER_API_KEY:
        try:
            result = chat(SUMMARY_PROMPT,
                          messages=[{"role": "user", "content": message}],
                          temperature=0.3, max_tokens=64)
            title = (result["content"] or "").strip().strip("'\"")
            if title:
                return title[:30]
        except Exception as exc:
            logger.warning("[OpenRouter] 标题生成失败，降级原消息：%s", exc)
    return message[:20]