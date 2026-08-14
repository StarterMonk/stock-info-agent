"""
v9 FastAPI 入口：多智能体 LangGraph 架构。

- Agent A：数据获取（AKShare 工具调用）
- Agent B：图表生成（ECharts 数据）
- Agent C：数据处理 + 模型预测（LightGBM/XGBoost/LSTM/GARCH）
- 超级节点：LLM 路由中心
- 短期记忆：session_store（SQLite）；长期记忆：memory_store
- 端口 8008
"""
import os, sys

# 将 agent_core 加入模块搜索路径
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_AGENT_CORE = os.path.normpath(os.path.join(_BACKEND_DIR, "..", "..", "agent_core"))
if _AGENT_CORE not in sys.path:
    sys.path.insert(0, _AGENT_CORE)

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
import analysis as analysis_mod
import stock_search
from graph_builder import build_graph

logger = logging.getLogger(__name__)

app = FastAPI(title="股票信息助手 v9 (LangGraph 多智能体)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# LangGraph 多智能体图（全局单例）
_multi_agent_graph = None


def _get_graph():
    global _multi_agent_graph
    if _multi_agent_graph is None:
        _multi_agent_graph = build_graph()
    return _multi_agent_graph

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

# 启动后台任务：检查股票名快照，缺失/过期则重建（不阻塞启动）
import threading


def _startup_snapshot_check():
    try:
        stock_search.ensure_ready()
    except Exception as exc:
        logger.warning("启动股票名快照检查失败（可稍后 POST /api/stocks/sync 手动重建）：%s", exc)


threading.Thread(target=_startup_snapshot_check, daemon=True).start()

STATIC_DIR = os.path.join(_BACKEND_DIR, "..", "frontend")


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


@app.get("/api/llm-status")
async def llm_status():
    """向 OpenRouter 发送 '你好' 测试消息，验证模型连通性。"""
    import httpx
    key = os.environ.get("OPENROUTER_API_KEY", "")
    model = os.environ.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    base = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    if not key:
        return {"ok": False, "error": "API Key 未配置", "model": model}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{base.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": "你好"}], "max_tokens": 20},
            )
            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"ok": True, "model": model, "reply": reply[:50]}
            return {"ok": False, "error": f"HTTP {resp.status_code}", "model": model}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100], "model": model}


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
        _auto_rename(session_id, message)
    except Exception as e:
        logger.error("chat_stream 处理失败: %s", e, exc_info=True)
        yield _sse("error", f"处理失败：{e}")
        store.add_message(session_id, "user", message)


# ---------------------------------------------------------------------------
# v9：LangGraph 多智能体流式端点
# ---------------------------------------------------------------------------
@app.post("/api/chat/multi")
async def chat_multi_stream(req: ChatRequest):
    """LangGraph 多智能体 SSE 流式端点。"""
    return StreamingResponse(
        _multi_agent_stream(req.session_id, req.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/chat/multi")
async def chat_multi_stream_get(session_id: str, message: str):
    """LangGraph 多智能体 GET SSE 端点。"""
    message = (message or "").strip()
    if not message or len(message) > 2000:
        return JSONResponse({"detail": "消息为空或超过 2000 字符"}, status_code=422)
    return StreamingResponse(
        _multi_agent_stream(session_id, message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _multi_agent_stream(session_id: str, message: str) -> AsyncGenerator[str, None]:
    """LangGraph 多智能体 SSE 流。"""
    yield _sse("start", "正在启动多智能体分析……")

    try:
        graph = _get_graph()
        store.add_message(session_id, "user", message)

        # 构建初始状态
        initial_state = {
            "messages": [{"role": "user", "content": message}],
            "user_query": message,
            "session_id": session_id,
            "ticker": "",
            "stock_name": "",
            "raw_data": {},
            "data_requests": [],
            "processed_data": {},
            "prediction": {},
            "anomaly_flags": [],
            "anomaly_resolutions": {},
            "data_sufficient": True,
            "chart_data": {},
            "charts": [],
            "current_step": "start",
            "next_agent": "",
            "needs_processing": False,
            "needs_chart": False,
            "needs_more_data": False,
            "c_retry_count": 0,
            "complexity": "simple",
            "error_log": [],
            "final_reply": "",
            "final_chart": {},
            "all_tool_calls": [],
        }

        # 在线程中运行 LangGraph
        result = await asyncio.to_thread(
            graph.invoke, initial_state,
            {"configurable": {"thread_id": session_id}}
        )

        # 发送工具调用事件
        for tc in result.get("all_tool_calls", []):
            yield _sse("tool", json.dumps(tc, ensure_ascii=False))

        # 发送异常事件（如有）
        anomalies = result.get("anomaly_flags", [])
        if anomalies:
            yield _sse("anomaly", json.dumps({
                "anomalies": anomalies,
                "question": "检测到数据异常，请选择处理方式",
            }, ensure_ascii=False))

        # 发送图表事件
        charts = result.get("charts", [])
        for chart in charts:
            yield _sse("chart", json.dumps(chart, ensure_ascii=False))

        # 发送最终回复
        final_reply = result.get("final_reply", "")
        if final_reply:
            for chunk in final_reply.split("\n"):
                if chunk.strip():
                    yield _sse("chunk", chunk.strip())

        # 发送数据事件
        yield _sse("data", json.dumps({
            "tool_calls": result.get("all_tool_calls", []),
            "chart": result.get("final_chart", {}),
        }, ensure_ascii=False))

        yield _sse("done", "完成")

        # 保存消息
        if final_reply:
            store.add_message(session_id, "assistant", final_reply)
        _auto_rename(session_id, message)

    except Exception as e:
        logger.error("multi_agent_stream 处理失败: %s", e, exc_info=True)
        yield _sse("error", f"处理失败：{e}")


# ---------------------------------------------------------------------------
# v9：异常处理端点
# ---------------------------------------------------------------------------
class AnomalyResolutionRequest(BaseModel):
    session_id: str
    anomaly_id: str
    resolution: str  # forward_fill / skip / interpolate / use_raw


@app.post("/api/anomaly/resolve")
async def resolve_anomaly(req: AnomalyResolutionRequest):
    """用户处理异常后，恢复图执行。"""
    return {"ok": True, "anomaly_id": req.anomaly_id, "resolution": req.resolution}


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@app.get("/api/analysis/options")
def analysis_options():
    """算法池（前端算法选择弹窗的数据源）。"""
    return {"algorithms": analysis_mod.ALGORITHMS}


class AnalysisRequest(BaseModel):
    code: str
    algorithm: str

    @field_validator("code")
    @classmethod
    def code_valid(cls, v: str) -> str:
        v = (v or "").strip()
        if not v.isdigit() or len(v) != 6:
            raise ValueError("股票代码需为 6 位数字")
        return v


@app.post("/api/analysis/run")
def analysis_run(req: AnalysisRequest):
    """按用户选择的算法执行数据分析，返回图表渲染所需数据。"""
    return analysis_mod.run_analysis(req.code, req.algorithm)


@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# v8：股票名称检索（本地快照，离线可用）
# ---------------------------------------------------------------------------
@app.get("/api/stocks/search")
def stocks_search(q: str = ""):
    """名称/拼音/拼音首字母模糊检索 → {query, total, results[{code,name,score}], tip}。"""
    return stock_search.search_stocks(q)


@app.post("/api/stocks/sync")
def stocks_sync():
    """手动触发全量股票名单快照同步（Sina 沪/深/北 + EM 兜底），并重建向量索引。"""
    return stock_search.sync_snapshot(force=True)


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
    _scheduler.add_job(stock_search.sync_snapshot, "cron", hour=15, minute=35,
                       misfire_grace_time=3600)
    _scheduler.start()
    logger.info("定时任务已注册：每日 15:30 日线增量同步；15:35 股票名快照同步")
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
