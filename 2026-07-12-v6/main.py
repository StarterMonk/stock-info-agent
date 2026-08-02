"""
v5 FastAPI 入口：基于 LangGraph 编排的 A 股股票信息助手。

与 v4 的差异：
- Agent 执行层由 agent_runner（手写循环）替换为 graph_agent（LangGraph StateGraph）
- 短期记忆交给 LangGraph 的 MemorySaver checkpointer（thread_id = session_id）
- 长期记忆仍由 memory_store 持久化（memory 节点在图收尾时写入）
- 端口 8004
"""
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
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

logger = logging.getLogger(__name__)

app = FastAPI(title="股票信息助手 v5 (LangGraph)")
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
    async def event_gen() -> AsyncGenerator[str, None]:
        yield _sse("start", "正在分析请求……")
        try:
            res = await asyncio.to_thread(agent.run_agent, req.message, session_id=req.session_id)
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
            store.add_message(req.session_id, "user", req.message)
            store.add_message(req.session_id, "assistant", res["reply"])
            # 长期记忆已由 graph_agent._memory_node 持久化，此处不再重复更新
            _auto_rename(req.session_id, req.message)
        except Exception as e:
            logger.error("chat_stream 处理失败: %s", e, exc_info=True)
            yield _sse("error", f"处理失败：{e}")
            store.add_message(req.session_id, "user", req.message)
    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


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
