"""
Gemini (Google AI Studio) LLM 接入层 —— v5 统一访问路径版。

特性：
- API Key 仅从环境变量 GEMINI_API_KEY 读取（不硬编码）。
- 模型默认 gemini-2.5-flash，可用 GEMINI_MODEL 覆盖。
- 通过 LangChain ChatGoogleGenerativeAI 统一所有 LLM 调用（意图解析、标题生成、记忆存储）。
- 支持「多轮 contents」：调用方传入完整对话历史，实现 stateful 多轮对话。
- 无 key 或失败时，提供关键词降级（仅用于意图解析）。
"""
import os
import json
import re
import logging

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = """你是一个专业的 A 股股票信息助手 Agent。
你可以调用一组工具来获取目标股票的各类信息（公司资料、历史行情、盘中分时、财务报表、分红、资金流向、财务指标、业绩报告等）。
工作流程：
1. 先理解用户意图，必要时调用工具获取真实数据；
2. 工具返回后，基于真实数据用中文清晰作答，并标注数据来源；
3. 若工具不可用或返回错误，如实说明，并尽量给出替代建议；
4. 结合对话历史与长期记忆，保持上下文连贯，主动关联用户此前关注的股票。
只输出面向用户的最终回答，不要输出内部工具调用细节。"""

SUMMARY_PROMPT = """你是一个对话标题生成器。请用不超过 20 个汉字，概括下面这条用户消息的核心意图，作为会话标题。只返回标题文本，不要引号、不要解释。"""


def _get_llm(system_prompt=SYSTEM_PROMPT, temperature=0.0):
    """惰性构建 ChatGoogleGenerativeAI 实例。"""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未设置")
    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=temperature,
        system_instruction=system_prompt,
    )


def _call_gemini(prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0, tools=None, contents=None):
    """统一 LLM 调用：使用 LangChain ChatGoogleGenerativeAI。

    保持与旧接口兼容的返回值格式，供 memory_store 和 parse_intent 使用。
    """
    llm = _get_llm(system_prompt=system_prompt, temperature=temperature)
    if contents is not None:
        # 将 Gemini 风格的 contents 转换为 LangChain 消息
        messages = []
        for c in contents:
            text = "".join(p.get("text", "") for p in c.get("parts", []))
            role = c.get("role", "user")
            if role == "model":
                messages.append(AIMessage(content=text))
            else:
                messages.append(HumanMessage(content=text))
    else:
        messages = [HumanMessage(content=prompt)]

    if tools:
        # 工具调用路径：绑定工具声明（主要用于向后兼容，主工具调用现由 graph_agent 处理）
        pass

    resp = llm.invoke(messages)
    # 返回与旧 _call_gemini 调用方兼容的格式
    text = resp.content if hasattr(resp, 'content') else str(resp)
    return {
        "candidates": [{
            "content": {
                "parts": [{"text": text}]
            }
        }]
    }


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
            logger.warning("[llm] Gemini 解析失败，降级关键词：%s", e, exc_info=True)
    return _keyword_parse(message)


def summarize_title(message):
    if GEMINI_API_KEY:
        try:
            text = _call_gemini(message, system_prompt=SUMMARY_PROMPT, temperature=0.3)["candidates"][0]["content"]["parts"][0]["text"]
            title = text.strip().strip('"').strip("'")
            if title:
                return title[:30]
        except Exception as e:
            logger.warning("[llm] 标题生成失败，降级原消息：%s", e, exc_info=True)
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
