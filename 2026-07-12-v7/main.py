"""
v7-openrouter FastAPI 入口：OpenRouter LLM 驱动的 A 股股票信息助手（含价格预测引擎）。

- Agent 执行层：graph_agent（OpenRouter 工具调用闭环，无 LangGraph）
- 短期记忆：session_store（SQLite）；长期记忆：memory_store
- LLM：OpenRouter REST（环境变量 OPENROUTER_API_KEY / OPENROUTER_MODEL）
- 启动前自动加载同目录 .env（不覆盖已有环境变量）
- 端口 8004
"""
import os

def _load_dotenv_file(path: str = ".env"):
    """极简 .env 加载：只处理 KEY=VALUE 行，不覆盖已存在的环境变量。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass

# 必须在导入 llm_client / graph_agent 之前执行，否则环境变量读取不到 .env
_load_dotenv_file()

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, Response
from pydantic import BaseModel, field_validator
from typing import Optional, List, AsyncGenerator
import os, json, datetime
import asyncio
import time as _time
import logging
import session_store as store
import graph_agent as agent
import memory_store as mem
import llm_client
import tools as tools_mod
import data_layer

logger = logging.getLogger(__name__)

app = FastAPI(title="股票信息助手 v7-openrouter (OpenRouter LLM + 价格预测引擎)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def observability_middleware(request, call_next):
    """可观测性中间件：记录每个 HTTP 请求的耗时。"""
    start = _time.time()
    response = await call_next(request)
    elapsed = _time.time() - start
    logger.info("HTTP %s %s → %d (%.2fs)",
                request.method, request.url.path, response.status_code, elapsed)
    return response

store.init_db()
data_layer.initialize_database()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class ChatRequest(BaseModel):
    session_id: str
    message: str

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("消息不能为空")
        if len(v) > 2000:
            raise ValueError("消息长度不能超过 2000 字符")
        return v


class ChatResponse(BaseModel):
    reply: str
    tool_calls: Optional[List[dict]] = None
    chart: Optional[dict] = None


@app.get("/api/sessions")
def list_sessions():
    return store.list_sessions()


@app.post("/api/sessions")
def create_session():
    return store.create_session()


@app.get("/api/sessions/{sid}/messages")
def get_messages(sid: str):
    return store.get_messages(sid)


class RenameRequest(BaseModel):
    title: str


@app.put("/api/sessions/{sid}")
def rename(sid: str, req: RenameRequest):
    store.rename_session(sid, req.title)
    return {"ok": True}


@app.delete("/api/sessions/{sid}")
def delete(sid: str):
    store.delete_session(sid)
    return {"ok": True}



@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    res = agent.run_agent(req.message, session_id=req.session_id)
    store.add_message(req.session_id, "user", req.message)
    store.add_message(req.session_id, "assistant", res["reply"])
    # 长期记忆已由 graph_agent._memory_node 持久化，此处不再重复更新
    _auto_rename(req.session_id, req.message)
    return ChatResponse(reply=res["reply"], tool_calls=res.get("tool_calls"),
                        chart=res.get("chart"))


def _auto_rename(sid: str, first_user_msg: str):
    cur = store.get_session(sid)
    if cur and cur["title"] in ("新会话", "", None):
        title = llm_client.summarize_title(first_user_msg)
        store.rename_session(sid, title)


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    return StreamingResponse(_stream_events(req.session_id, req.message),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/chat/stream")
async def chat_stream_get(session_id: str, message: str):
    """GET 版 SSE：浏览器 EventSource 仅支持 GET，前端 /api/chat/stream?session_id=&message= 走这里。"""
    message = (message or "").strip()
    if not message or len(message) > 2000:
        return JSONResponse({"detail": "消息为空或超过 2000 字符"}, status_code=422)
    return StreamingResponse(_stream_events(session_id, message),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _stream_events(session_id: str, message: str) -> AsyncGenerator[str, None]:
    yield _sse("start", "正在分析请求……")
    try:
        res = await asyncio.to_thread(agent.run_agent, message, session_id=session_id)
        for tc in res.get("tool_calls", []):
            yield _sse("tool", json.dumps(tc, ensure_ascii=False))
        for chunk in res["reply"].split("\n"):
            if chunk.strip():
                yield _sse("chunk", chunk.strip())
        yield _sse("data", json.dumps({
            "tool_calls": res.get("tool_calls"),
            "chart": res.get("chart"),
        }, ensure_ascii=False))
        yield _sse("done", "完成")
        store.add_message(session_id, "user", message)
        store.add_message(session_id, "assistant", res["reply"])
        # 长期记忆已由 graph_agent._memory_node 持久化，此处不再重复更新
        _auto_rename(session_id, message)
    except Exception as e:
        logger.error("chat_stream 处理失败: %s", e, exc_info=True)
        yield _sse("error", f"处理失败：{e}")
        store.add_message(session_id, "user", message)


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@app.get("/api/predict/{code}")
def predict_price(code: str, horizon: int = 10):
    """价格预测 REST 直连（不经过 LLM，供前端或其他程序独立调用）。"""
    return tools_mod.get_price_prediction(code, horizon=horizon)


# ---------------------------------------------------------------------------
# v7：每日收盘后增量同步日线（APScheduler；若未安装或异常则静默跳过）
# ---------------------------------------------------------------------------
try:
    from apscheduler.schedulers.background import BackgroundScheduler

    def _daily_price_sync_job():
        for _code in tools_mod._LOCAL_NAME_MAP.values():
            try:
                data_layer.backfill(_code, years=3)
            except Exception:
                logger.exception("日线增量同步失败 code=%s", _code)

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_daily_price_sync_job, "cron", hour=15, minute=30,
                       misfire_grace_time=3600)
    _scheduler.start()
    logger.info("日线增量定时任务已注册：每日 15:30")
except Exception:
    logger.warning("APScheduler 未安装或启动失败，定时增量同步不可用")


@app.get("/api/sessions/{sid}/export")
def export_session(sid: str, fmt: str = "markdown"):
    msgs = store.get_messages(sid)
    sessions = store.list_sessions()
    title = next((s["title"] for s in sessions if s["id"] == sid), "会话")
    long_memory = mem.get_long_memory(sid)
    if fmt == "json":
        return JSONResponse({"title": title, "messages": msgs, "long_memory": long_memory})
    lines = [f"# {title}", "", f"> 导出时间：{datetime.datetime.now().isoformat(timespec='seconds')}", ""]
    if long_memory:
        lines.append("## 长期记忆")
        lines.append(long_memory)
        lines.append("")
    for m in msgs:
        role = "用户" if m["role"] == "user" else "助手"
        lines.append(f"## {role}（{m['created_at']}）")
        lines.append(m["content"])
        lines.append("")
    return JSONResponse({"markdown": "\n".join(lines)})


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
