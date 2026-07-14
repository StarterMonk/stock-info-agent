# 股票信息助手（Stock Info Agent）

一个面向个股的**股票信息智能助手**，支持查询上市板块、主营业务、历史/盘中行情、财务报表、分红、业绩等多维度信息。系统采用「Agent + 工具调用」架构，数据主要来自 [AKShare](https://akshare.akfamily.xyz/) 中提供的 API，并辅以公开财经网站兜底。

> 先说在前面：这是我一边学 AI Agent、一边炒股时顺手做的小练习，纯属练手踩坑用。代码和思路都不算成熟，里面大概率有不少粗糙、甚至不对的地方。如果您刚好逛到这儿，欢迎随时拍砖、提建议，先谢过啦 🙏

> 本文档提供**中文版**与 **English Version** 两个版本，内容一致，挑顺眼的看就行。

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

> 项目以**渐进式版本迭代**方式演进：v1 → v4 已落地验证，v5（LangGraph 架构）规划中。每个版本独立成文件夹，方便我自己回头对比、回滚，也方便你挑感兴趣的版本看。

---

## 技术栈

| 层         | 选型                                                                  |
| ---------- | --------------------------------------------------------------------- |
| 后端       | FastAPI + Uvicorn                                                     |
| LLM        | Google Gemini / Gemma 4 31B（`gemma-4-31b-it`），仅经环境变量读 Key |
| 数据       | AKShare（新浪/巨潮/同花顺/东财等多源）                                |
| 存储       | SQLite（会话、消息、长期记忆）                                        |
| 前端       | 原生 JS + ECharts 5（K 线图），SSE 流式渲染                           |
| Agent 编排 | v4 手写 ReAct 闭环；v5 计划用 LangGraph                               |

---

## 版本架构与设计

下面是我自己边做边记的「踩坑笔记」，写得比较随意，但尽量把每个版本为什么这么改讲清楚。

### v1 — 基础查询助手

- **目标**：能用 AKShare 查单只股票的「上市详情」与「历史日线」。
- **架构**：
  - `main.py`：FastAPI，`/api/sessions` 会话 CRUD、`/api/chat` 同步问答、静态资源挂载。
  - `session_store.py`：SQLite 持久化会话与消息。
  - `agent_runner.py`：`get_profile`（cninfo）、`get_history`（新浪日线）、`_resolve_code`、`web_fallback`。
- **关键决策（踩坑）**：东方财富 `stock_individual_info_em` / `stock_zh_a_hist` 在我这台机器上被代理拦了（ProxyError），折腾半天没搞定，就换成了 `stock_profile_cninfo` + `stock_zh_a_daily`（新浪源），反而更稳。
- **端口**：8000。

### v2 — 流式与兜底

- **新增**：
  - `/api/chat/stream`：SSE 流式输出，打字机效果，体验好很多。
  - `/api/sessions/{sid}/export`：会话导出（Markdown / JSON），方便复盘。
  - `web_fallback`：AKShare 抽风时，去新浪/东方财富个股页兜底抓点信息。
- **端口**：8001。

### v3 — LLM 意图解析 + 安全

- **新增**：
  - `llm_client.py`：接上 Gemini/Gemma 的 `generateContent`，做意图解析（`parse_intent`）和会话标题生成（`summarize_title`）。
  - `get_intraday`：盘中分时（新浪分钟线），还能定位到具体某一分钟。
  - 第一条消息发完，自动把会话标题换成 LLM 生成的摘要，侧边栏清爽多了。
- **安全加固（很重要）**：一开始图省事把 API Key 写死在代码里，后来意识到太危险，改成只从 `GEMINI_API_KEY` 环境变量读；顺手加了 `.env.example` 和 `.gitignore`，别把密钥提交上去。
- **端口**：8002。

### v4 — 多轮记忆 + 工具调用（当前最新可用版）

- **目标**：让 Agent 自己决定该调哪些工具，并且能记住之前聊过啥。
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
- **工具层 `tools.py`**（覆盖目标股票全部维度，这块是我花时间最多的）：

  | 工具                 | 维度               | 状态                                             |
  | -------------------- | ------------------ | ------------------------------------------------ |
  | `get_profile`      | 公司资料/板块/主营 | ✅ cninfo                                        |
  | `get_history`      | 历史日 K 线        | ✅ 新浪日线                                      |
  | `get_intraday`     | 盘中分时           | ✅ 新浪分钟线                                    |
  | `get_financials`   | 三大财务报表       | ✅ 新浪财报                                      |
  | `get_dividend`     | 分红送配           | ✅ cninfo                                        |
  | `get_indicators`   | 估值与财务指标     | ✅ 财务分析指标                                  |
  | `get_key_metrics`  | 主要财务摘要       | ✅ 同花顺摘要                                    |
  | `get_forecast`     | 业绩报告/预告      | ✅ 东财业绩报表                                  |
  | `get_capital_flow` | 个股资金流向       | ⚠️ 东财接口被代理拦截，API 位置留空 + 替代建议 |

- **记忆层 `memory_store.py`**：`long_memory` 表 + 让 LLM 把每轮结果抽成稳定事实存起来，下一轮再喂回去。
- **前端**：实时显示工具调用进度（🔧），K 线图照旧能画。
- **端口**：8003。

### v5 — LangGraph 编排（规划中，还没写）

- **目标**：把 v4 里我手搓的工具调用循环，换成 [LangGraph](https://github.com/langchain-ai/langgraph) 来编排，图结构更清晰、好调试也好扩展。
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

> 这块我还在学，等踩完坑再补上，欢迎有经验的朋友指条明路。

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

> 小提示：不填 `GEMINI_API_KEY` 也能跑，只是会退化成「关键词驱动」的简化模式，用来体验流程完全够用。

---

## 已知限制

- 我这台机器网络下，东方财富 push2 行情接口被代理拦了，`get_capital_flow`（个股资金流向）暂时用不了；我按需求把 API 调用位置先留空，并给了替代方案（北向/板块资金流）。如果你那边网络通，填上对应调用就行。
- LLM 工具调用闭环需要配置 `GEMINI_API_KEY`；没配的话走关键词降级路径（已验证可用）。

## 许可证

MIT（如需商用请自行确认数据源合规）。

---

---

# English Version

# Stock Info Agent

A small **stock-information assistant** for individual A-share stocks. It can look up things like the listing board, main business, historical/intraday prices, financial statements, dividends, earnings, and more. The architecture is "Agent + tool calling", with data mainly from the [AKShare](https://akshare.akfamily.xyz/) APIs, plus a fallback to public finance websites.

> A quick disclaimer up front: this is a side project I built while learning AI Agents (and while dabbling in the stock market). It's purely for practice and for stepping on as many rakes as possible. The code and design are far from polished, and there are very likely rough — or simply wrong — spots. If you happen to stumble upon this repo, feedback and suggestions are more than welcome. Thank you 🙏

> This document comes in **中文版 (Chinese)** and **English Version** — same content, pick whichever you prefer.

---

## Project Structure

```
2026-07-11-Stock-Collector/
├── README.md                 # This file: overview & version notes
├── stock-info.agent.md       # VS Code Agent definition (stock info specialist)
├── 2026-07-12-v1/            # Baseline: FastAPI + single-turn query
├── 2026-07-12-v2/            # + SSE streaming + session export + web fallback
├── 2026-07-12-v3/            # + LLM (Gemini/Gemma) intent parsing + intraday + security
├── 2026-07-12-v4/            # + multi-turn memory + tool calling (full dimensions)
└── 2026-07-12-v5/            # (Planned) LangGraph-orchestrated Agent
```

> The project evolves **incrementally**: v1 → v4 are implemented and verified; v5 (LangGraph) is planned. Each version lives in its own folder so I can compare/rollback, and you can jump to whichever version interests you.

---

## Tech Stack

| Layer        | Choice                                                                |
| ------------ | --------------------------------------------------------------------- |
| Backend      | FastAPI + Uvicorn                                                     |
| LLM          | Google Gemini / Gemma 4 31B (`gemma-4-31b-it`), key read from env only |
| Data         | AKShare (Sina / CNINFO / THS / Eastmoney, multi-source)              |
| Storage      | SQLite (sessions, messages, long-term memory)                        |
| Frontend     | Vanilla JS + ECharts 5 (candlestick), SSE streaming                  |
| Agent orchestration | v4: hand-written ReAct loop; v5: planned with LangGraph      |

---

## Version Architecture & Design

Below are my casual "learning notes" from building each version — written loosely, but I try to explain *why* each change was made.

### v1 — Baseline query assistant

- **Goal**: query a stock's "listing profile" and "historical daily prices" via AKShare.
- **Architecture**:
  - `main.py`: FastAPI, `/api/sessions` CRUD, `/api/chat` sync Q&A, static mount.
  - `session_store.py`: SQLite persistence for sessions & messages.
  - `agent_runner.py`: `get_profile` (cninfo), `get_history` (Sina daily), `_resolve_code`, `web_fallback`.
- **Key decision (a gotcha)**: Eastmoney's `stock_individual_info_em` / `stock_zh_a_hist` were blocked by a proxy on my machine (ProxyError). After struggling with it, I switched to `stock_profile_cninfo` + `stock_zh_a_daily` (Sina source), which turned out more stable.
- **Port**: 8000.

### v2 — Streaming & fallback

- **Added**:
  - `/api/chat/stream`: SSE streaming output (typewriter effect), much nicer UX.
  - `/api/sessions/{sid}/export`: session export (Markdown / JSON) for review.
  - `web_fallback`: when AKShare misbehaves, scrape Sina/Eastmoney stock pages as a backup.
- **Port**: 8001.

### v3 — LLM intent parsing + security

- **Added**:
  - `llm_client.py`: wired up Gemini/Gemma `generateContent` for intent parsing (`parse_intent`) and session-title generation (`summarize_title`).
  - `get_intraday`: intraday minute bars (Sina), can locate a specific minute.
  - After the first message, the session title auto-updates to an LLM summary — sidebar stays tidy.
- **Security hardening (important)**: I originally hardcoded the API key for convenience, then realized how risky that was and switched to reading only from the `GEMINI_API_KEY` env var; added `.env.example` and `.gitignore` so secrets never get committed.
- **Port**: 8002.

### v4 — Multi-turn memory + tool calling (latest usable version)

- **Goal**: let the Agent decide which tools to call, and remember what was discussed earlier.
- **Architecture**:
  ```
  user message
    │
    ├─ short-term memory: last 12 turns → Gemini contents
    ├─ long-term memory: long_memory table → injected into system context
    ▼
  agent_runner.run_agent()
    │  LLM generates (tools=TOOL_DECLARATIONS)
    ├─ has functionCall → run tools.call_tool → feed back functionResponse → regenerate
    └─ plain text → return
    │
    └─ per-turn tool-result summary → memory_store.update_long_memory() persists
  ```
- **Tool layer `tools.py`** (covers all dimensions for the target stock — the part I spent most time on):

  | Tool                 | Dimension                | Status                                          |
  | -------------------- | ------------------------ | ----------------------------------------------- |
  | `get_profile`      | profile / board / business | ✅ cninfo                                     |
  | `get_history`      | historical daily K-line  | ✅ Sina daily                                   |
  | `get_intraday`     | intraday minute bars     | ✅ Sina minute                                  |
  | `get_financials`   | three financial statements | ✅ Sina financials                            |
  | `get_dividend`     | dividends / bonuses      | ✅ cninfo                                       |
  | `get_indicators`   | valuation & financial metrics | ✅ financial-analysis indicator             |
  | `get_key_metrics`  | key financial summary    | ✅ THS summary                                  |
  | `get_forecast`     | earnings report / forecast | ✅ Eastmoney earnings                          |
  | `get_capital_flow` | individual capital flow  | ⚠️ Eastmoney blocked by proxy; API left empty + alternative suggested |

- **Memory layer `memory_store.py`**: `long_memory` table + LLM distills each turn into stable facts, fed back next round.
- **Frontend**: shows live tool-call progress (🔧), candlestick chart still works.
- **Port**: 8003.

### v5 — LangGraph orchestration (planned, not yet written)

- **Goal**: replace the hand-rolled tool-calling loop in v4 with [LangGraph](https://github.com/langchain-ai/langgraph) for a declarative, observable, extensible Agent graph.
- **Design (StateGraph / ReAct)**:
  ```
  START → agent(LLM+bind_tools, inject long-term memory)
            │ tools_condition
      ┌─────┴──────┐
   has call     no call
    │              │
  tools(ToolNode)  END
    │
  agent ←──┘
    │
  memory(distill long-term) → END
  ```
- **Reuse**: v4's `tools.py`, `memory_store.py`, `session_store.py`, `static/`.
- **New**: `graph_agent.py` (LangGraph orchestration), `main.py` calls `graph_app.invoke(...)`.
- **Deps**: `langchain`, `langgraph`, `langchain-google-genai`.
- **Port**: 8004 (planned).

> I'm still learning this part; I'll fill it in after I've stepped on the rakes. Pointers from anyone with experience are very welcome.

---

## Quick Start (using v4 as example)

```bash
cd 2026-07-12-v4
source ../2026-07-12-v1/.venv/bin/activate   # reuse v1's virtualenv
pip install -r requirements.txt
export GEMINI_API_KEY="your-key"              # optional; empty → keyword fallback
export V4_DB_PATH="$(pwd)/v4_sessions.db"
uvicorn main:app --port 8003
```

Open http://127.0.0.1:8003 in your browser.

> Tip: it runs fine without `GEMINI_API_KEY` too — it just degrades to a "keyword-driven" simplified mode, which is enough to try the flow.

---

## Known Limitations

- On my network, Eastmoney's push2 quote interface is blocked by a proxy, so `get_capital_flow` (individual capital flow) is temporarily unavailable. Per the requirement, I left the API call location empty and provided an alternative (northbound / sector fund flow). If your network allows it, just fill in the corresponding call.
- The LLM tool-calling loop needs `GEMINI_API_KEY`; without it, the keyword fallback path is used (verified working).

## License

MIT (if used commercially, please confirm data-source compliance yourself).
