# A 股股票信息助手（Stock Info Agent）

一个面向 A 股个股的**股票信息智能助手**，支持查询上市板块、主营业务、历史/盘中行情、财务报表、分红、业绩等多维度信息。系统采用「Agent + 工具调用」架构，数据主要来自 [AKShare](https://akshare.akfamily.xyz/)，并辅以公开财经网站兜底。

> 项目以**渐进式版本迭代**方式演进：v1 → v4 已落地验证，v5（LangGraph 架构）规划中。每个版本独立成文件夹，便于对比与回滚。

---

## 目录结构

```
2026-07-11-Stock-Collector/
├── README.md                 # 本文件：项目总览与版本架构记录
├── stock-info.agent.md       # VS Code Agent 定义（股票信息专员）
├── 2026-07-12-v1/            # 基础版：FastAPI + 单轮查询
├── 2026-07-12-v2/            # + SSE 流式 + 会话导出 + 网站兜底
├── 2026-07-12-v3/            # + LLM(Gemini/Gemma) 意图解析 + 盘中查询 + 安全加固
├── 2026-07-12-v4/            # + 多轮记忆 + 工具调用(Tool Calling) 全维度
└── 2026-07-12-v5/            # (规划) LangGraph 编排的 Agent 架构
```

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI + Uvicorn |
| LLM | Google Gemini / Gemma 4 31B（`gemma-4-31b-it`），仅经环境变量读 Key |
| 数据 | AKShare（新浪/巨潮/同花顺/东财等多源） |
| 存储 | SQLite（会话、消息、长期记忆） |
| 前端 | 原生 JS + ECharts 5（K 线图），SSE 流式渲染 |
| Agent 编排 | v4 手写 ReAct 闭环；v5 计划用 LangGraph |

---

## 版本架构与设计

### v1 — 基础查询助手
- **目标**：能用 AKShare 查单只股票的「上市详情」与「历史日线」。
- **架构**：
  - `main.py`：FastAPI，`/api/sessions` 会话 CRUD、`/api/chat` 同步问答、静态资源挂载。
  - `session_store.py`：SQLite 持久化会话与消息。
  - `agent_runner.py`：`get_profile`（cninfo）、`get_history`（新浪日线）、`_resolve_code`、`web_fallback`。
- **关键决策**：东方财富 `stock_individual_info_em` / `stock_zh_a_hist` 在本机被代理拦截（ProxyError），改用 `stock_profile_cninfo` + `stock_zh_a_daily`（新浪）。
- **端口**：8000。

### v2 — 流式与兜底
- **新增**：
  - `/api/chat/stream`：SSE 流式输出。
  - `/api/sessions/{sid}/export`：会话导出（Markdown / JSON）。
  - `web_fallback`：AKShare 不可用时检索新浪/东方财富个股页补充。
- **端口**：8001。

### v3 — LLM 意图解析 + 安全
- **新增**：
  - `llm_client.py`：接入 Gemini/Gemma `generateContent`，做意图解析（`parse_intent`）与会话标题生成（`summarize_title`）。
  - `get_intraday`：盘中分时（新浪分钟线），支持定位具体时刻。
  - 首条消息后自动将会话标题更新为 LLM 摘要。
- **安全加固**：移除硬编码 API Key，改为仅从 `GEMINI_API_KEY` 环境变量读取；新增 `.env.example` 与 `.gitignore`。
- **端口**：8002。

### v4 — 多轮记忆 + 工具调用（当前最新可用版）
- **目标**：Agent 自主决定调用哪些工具，并具备跨轮记忆。
- **架构**：
  ```
  用户消息
    │
    ├─ 短期记忆：最近 12 轮 messages → Gemini contents
    ├─ 长期记忆：long_memory 表 → 注入 system 上下文
    ▼
  agent_runner.run_agent()
    │  LLM 生成（tools=TOOL_DECLARATIONS）
    ├─ 含 functionCall → 执行 tools.call_tool → 回填 functionResponse → 再生成
    └─ 纯文本 → 返回
    │
    └─ 每轮工具结果摘要 → memory_store.update_long_memory() 持久化
  ```
- **工具层 `tools.py`**（覆盖目标股票全部维度）：
  | 工具 | 维度 | 状态 |
  |---|---|---|
  | `get_profile` | 公司资料/板块/主营 | ✅ cninfo |
  | `get_history` | 历史日 K 线 | ✅ 新浪日线 |
  | `get_intraday` | 盘中分时 | ✅ 新浪分钟线 |
  | `get_financials` | 三大财务报表 | ✅ 新浪财报 |
  | `get_dividend` | 分红送配 | ✅ cninfo |
  | `get_indicators` | 估值与财务指标 | ✅ 财务分析指标 |
  | `get_key_metrics` | 主要财务摘要 | ✅ 同花顺摘要 |
  | `get_forecast` | 业绩报告/预告 | ✅ 东财业绩报表 |
  | `get_capital_flow` | 个股资金流向 | ⚠️ 东财接口被代理拦截，API 位置留空 + 替代建议 |
- **记忆层 `memory_store.py`**：`long_memory` 表 + LLM 抽取合并稳定事实。
- **前端**：实时展示工具调用进度（🔧），K 线图渲染。
- **端口**：8003。

### v5 — LangGraph 编排（规划中）
- **目标**：用 [LangGraph](https://github.com/langchain-ai/langgraph) 替代 v4 手写的工具调用闭环，获得声明式、可观测、易扩展的 Agent 图。
- **设计（StateGraph / ReAct）**：
  ```
  START → agent(LLM+bind_tools, 注入长期记忆)
            │ tools_condition
      ┌─────┴──────┐
   有调用        无调用
    │              │
  tools(ToolNode)  END
    │
  agent ←──┘
    │
  memory(抽取长期记忆) → END
  ```
- **复用**：v4 的 `tools.py`、`memory_store.py`、`session_store.py`、`static/`。
- **新增**：`graph_agent.py`（LangGraph 编排）、`main.py` 改为调用 `graph_app.invoke(...)`。
- **依赖**：`langchain`、`langgraph`、`langchain-google-genai`。
- **端口**：8004（计划）。

---

## 快速开始（以 v4 为例）

```bash
cd 2026-07-12-v4
source ../2026-07-12-v1/.venv/bin/activate   # 复用 v1 的虚拟环境
pip install -r requirements.txt
export GEMINI_API_KEY="你的Key"               # 可选，留空则降级关键词驱动
export V4_DB_PATH="$(pwd)/v4_sessions.db"
uvicorn main:app --port 8003
```
浏览器打开 http://127.0.0.1:8003

---

## 已知限制
- 本机网络下东方财富 push2 行情接口被代理拦截，`get_capital_flow`（个股资金流向）暂不可用；已留空 API 位置并给出替代方案（北向/板块资金流）。
- LLM 工具调用闭环需配置 `GEMINI_API_KEY`；未配置时走关键词降级路径（已验证可用）。

## 许可证
MIT（如需商用请自行确认数据源合规）。
