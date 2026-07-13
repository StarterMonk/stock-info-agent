# 股票信息助手 — 第三版（2026-07-12-v3）

在 v2 基础上接入 LLM（Google AI Studio / Gemini），并新增盘中（分时）查询能力。

## 新增功能（相对 v2）
- **LLM 意图解析（Gemma 4 31B）**：`llm_client.py` 通过 Gemini API 的 `generateContent` 端点调用 **Gemma 4 31B**（`gemma-4-31b-it`，可用 `GEMINI_MODEL` 覆盖）将自然语言解析为结构化查询参数。API Key **仅从环境变量 `GEMINI_API_KEY` 读取，不硬编码**；留空时自动降级为关键词启发式解析。
- **会话标题自动摘要**：用户发送首条消息后，后端用 LLM 将该消息概括为会话标题（前端 `done` 事件后刷新侧栏）；无 Key 时降级为截断的原消息。
- **盘中/分时查询**：`agent_runner.get_intraday` 用 AKShare `stock_zh_a_minute`（新浪分钟线）按日期+具体时间（如 14:00）定位分钟级行情，前端 K 线图支持分时展示。

## 安全说明
- API Key 已移除硬编码，改为 `export GEMINI_API_KEY="..."` 或写入 `.env`（已加入 `.gitignore`）。
- 提供了 `.env.example` 作为模板。

## 测试结论：贵州茅台 2026-07-10 14:00 查询
✅ **执行成功**。返回该日 14:00:00 这一分钟 bar：
- 开:1198.27 收:1198.27 高:1198.27 低:1197.89 量:8000
- 来源：AKShare（新浪财经分钟线）

### 复测（填入 Gemini API Key 后）发现并修复的问题
1. **Gemini 返回 429 Too Many Requests**：Key 被限流（免费额度），LLM 解析失败。系统已正确**降级为关键词解析**，仍给出正确答案。
   - 修补：无需改代码；若需启用 LLM，请更换/升级 Key 或降低调用频率。
2. **按名称查询代码失败**：`_resolve_code` 依赖 AKShare 名称接口（`stock_info_a_code_name`），该接口在本机被代理拦截返回空，导致「贵州茅台」无法解析为 600519。
   - 修补：新增 `_LOCAL_NAME_MAP` 本地常用股票名称→代码映射，并在 `run_agent` 中优先用 LLM 返回的 `name` 字段查本地映射。
3. **历史行情日期带横线导致 0 条**：LLM/关键词解析出的 `start_date` 为 `2024-01-02`（带横线），而 `get_history` 内部按 `20240102`（无横线）比较，过滤后为空。
   - 修补：`run_agent` 调用 `get_history` 前对日期 `replace("-","")`。

### 早期（v3 首轮）已修复
- 日期误解析：正则误吞股票代码 `600519` → 改为仅匹配明确分隔符格式。
- 时间匹配错位：`str.contains("1400")` 误命中分钟 → 用正则提取 `HHMM` 精确匹配。

## 取数方式（对应代理定义）
- 上市详情：AKShare `stock_profile_cninfo`（巨潮资讯网）
- 历史日线：AKShare `stock_zh_a_daily`（新浪财经日线）
- 盘中分时：AKShare `stock_zh_a_minute`（新浪财经分钟线）
- 网站兜底：新浪财经 / 东方财富网页检索（方式二）

## 运行
```bash
source ../2026-07-12-v1/.venv/bin/activate
# 启用 Gemma 4 31B 意图解析（必须设置 Key）
export GEMINI_API_KEY="你的key"
# 可选：覆盖模型（默认 gemma-4-31b-it）
# export GEMINI_MODEL="gemma-4-31b-it"
uvicorn main:app --host 127.0.0.1 --port 8002
# 浏览器打开 http://127.0.0.1:8002
```

## 目录结构
```
2026-07-12-v3/
├── main.py            # FastAPI（含 SSE / 导出 / intraday）
├── session_store.py   # SQLite 会话持久化
├── agent_runner.py    # 代理逻辑：代码识别 + AKShare + 盘中 + 网站兜底
├── llm_client.py      # Gemini LLM 意图解析（Key 留空降级）
├── requirements.txt
├── README.md
└── static/
    ├── index.html
    ├── app.js         # SSE 流式 + 导出 + 分时图
    └── style.css
```

## 已知限制 / 下一步
- LLM 仅做意图解析，未做多轮对话记忆增强
- 网站兜底仅返回页面标题与链接
- 盘中数据依赖新浪分钟线，盘中实时性受接口延迟影响
