# 🦾 Stock-Info-Agent · A 股智能助手

### LLM 驱动的 A 股对话式信息助手 — OpenRouter 接入 · 11 大工具 · 价格预测引擎 · ECharts 可视化

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-teal?logo=fastapi&logoColor=white)
![OpenRouter](https://img.shields.io/badge/LLM-OpenRouter-orange)
![AKShare](https://img.shields.io/badge/AKShare-1.14%2B-green)
![SARIMA](https://img.shields.io/badge/预测-SARIMA%20%2B%20置信带-purple)
![Release](https://img.shields.io/github/v/release/StarterMonk/stock-info-agent?color=blue)

---

## 🇨🇳 第一部分 · 中文

### 这是什么？

一个**用自然语言对话 A 股数据**的智能体：你像和朋友聊天一样发问，它调用专业工具获取真实行情，给出结构化回答，并绘制图表。

```text
你：「预测一下 600519 未来 10 个交易日的走势」
它：调用「价格预测引擎」→ SARIMA + 技术指标建模
    → 「方向偏多（概率 0.59）· 支撑 1151 · 压力 1363」
    → 绘出「中位价 + 置信区间」预测带图表 📈
```

### ✨ 特性亮点

| 能力 | 说明 |
|------|------|
| 🧠 **LLM 驱动的 Agent** | OpenRouter 兼容任意 OpenAI 系模型（默认免费模型开箱即用），原生工具调用闭环，支持多轮追问 |
| 🔧 **11 个专业股票工具** | 公司资料 / 历史行情 / 分时 / 财务三表 / 分红 / 资金流 / 常用指标 / 关键指标 / 机构预测 / 技术指标 / 价格预测 |
| 🔮 **价格预测引擎** | SARIMA(1,1,1) 中位价 + EMA 基线兜底 + 滚动波动率置信区间（1.96σ√h）；walk-forward 回测门禁（准确率 ≥55% 且跑赢随机游走 5%） |
| 📊 **技术指标库** | MA5/20/60、MACD、RSI、KDJ、BOLL、ATR 及多空状态快照，20+ 指标 |
| 📈 **ECharts 可视化** | 预测区间带、分时走势、K 线图，浏览器直出 |
| ⚡ **SSE 流式对话** | Chat 工具调用、步骤、回复逐段流式推送，体验丝滑 |
| 🧠 **记忆系统** | 短期记忆（会话内多轮上下文）+ 长期记忆（跨会话事实沉淀） |
| 🛡️ **稳健降级** | LLM 掉线/限流时自动降级为关键词模式，11 个核心工具依然可用 |
| 🗓️ **每日自动同步** | APScheduler 每交易日 15:30 增量同步日线（`daily_price_history`），预测留痕（`prediction_history`） |

### 🚀 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置密钥（不配置也"零"可用——自动降级为关键词模式）
cp .env.example .env     # Windows: copy .env.example .env
# 填入 OPENROUTER_API_KEY（OpenRouter 免费 Key 即可）
# 默认模型实测可用：openai/gpt-oss-20b:free

# 3. 启动服务
uvicorn main:app --port 8004
```

打开浏览器访问 **http://127.0.0.1:8004**，即可开聊：

```text
· 贵州茅台属于哪个板块？它上市时间是什么？
· 查询 000001 今天的资金流情况
· 数据库里 600519 最近怎么走？
· 用技术指标评估一下 300750
· 预测 601318 未来 20 个交易日，行情分享一下
```

### 🏗️ 架构设计

```text
浏览器 (ECharts Web UI)
   │  SSE 流式
   ▼
FastAPI (main.py) ──► 会话存储(SQLite)
   │
   ▼
Agent 闭环 (graph_agent.py，工具调用 ≤6 轮)
   │  ├─ LLM 客户端 (llm_client.py → OpenRouter REST)
   │  ├─ 11 个工具 (tools.py → AKShare)
   │  └─ 记忆 (memory_store / session_store)
   │
   ▼
价格预测引擎 (models.py → SARIMA + 置信带；features.py → 20+ 指标)
   └─ 数据层 (data_layer.py → daily_price_history / prediction_history)
```

| 模块 | 职责 |
|------|------|
| `llm_client.py` | OpenRouter REST 接入、意图解析、标题摘要、关键词降级 |
| `graph_agent.py` | 工具调用闭环、图表数据组装、降级路由 |
| `tools.py` | 11 个数据工具（AKShare，带超时与缓存） |
| `data_layer.py` | 日线回填/增量同步、预测留痕（表名全英文） |
| `features.py` | 技术指标计算与多空状态快照 |
| `models.py` | SARIMA/EMA 预测与置信区间 |
| `backtest.py` | walk-forward 回测门禁 |
| `session_store.py` / `memory_store.py` | 短期会话 / 长期记忆持久化 |
| `main.py` | FastAPI 路由、SSE 流式、APScheduler 定时同步 |

### 📁 项目结构

```
2026-07-12-v7/            ← 当前主版本（OpenRouter LLM + 价格预测引擎）⭐
   main.py · llm_client.py · graph_agent.py · tools.py
   data_layer.py · features.py · models.py · backtest.py
   session_store.py · memory_store.py · reporter.py
   static/（Web UI + ECharts）
2026-07-12-v6/            ← 历史版：生产级优化（LangGraph 编排）…………
2026-07-12-v5/ ~ v1/      ← 早期演进版本（留存供研究参考）
```

### 🔗 一键运行与发布

- 最新发布包：见右侧 **Releases**（v1.0.0，含完整代码 zip）
- 变更历史：Git History / PR 均可追溯
- 数据表命名规范：一律使用英文全称（`daily_price_history`、`prediction_history`）

### ⚠️ 免责声明

> 本项目仅供学习与研究，不构成任何投资建议。预测基于历史行情的统计推断，股市有风险，决策需谨慎。

---

## 🇺🇸 Part 2 · English

### About

**Stock-Info-Agent** is a conversational A-share (China stock market) assistant powered by LLMs. Ask it in plain language, and it retrieves real market data via **AKShare**, analyzes with a **price-forecasting engine**, and answers with structured reports and interactive **ECharts** visualizations.

### Highlights

- 🤖 LLM-driven agent with native function calling (OpenRouter, OpenAI-compatible; works with free models out of the box)
- 🔧 11 professional stock tools: profile, history, intraday, financials, dividends, capital flow, technical indicators, ratings and price prediction
- 🔮 Statistical prediction engine: SARIMA(1,1,1) median + EMA fallback + volatility confidence bands, gated by walk-forward backtests (≥55% accuracy, +5% over random walk)
- ⚡ SSE streaming chat: incremental chunks, live tool-call steps, real-time charts
- 🧠 Hybrid memory: short-term conversation context + long-term cross-session facts
- 🛡️ Graceful degradation: keyword mode when the LLM API is unavailable
- 🌅 Scheduled daily sync (15:30 CST) into `daily_price_history`; predictions logged in `prediction_history`

### Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --port 8004
```

Open **http://127.0.0.1:8004** and start chatting.

### Architecture

```
Web UI (ECharts) ⇄ FastAPI (main.py) ⇄ Agent loop (≤6 tool rounds)
                  ⇄ OpenRouter LLM + 11 tools (AKShare) + Memory
                  ⇄ Price engine (SARIMA + confidence bands)
```

### License & Disclaimer

MIT License. This project is for educational and research purposes only — nothing here is financial advice.

---

> 更多细节与版本演进记录见 `2026-07-12-v7/README.md` / the `2026-07-12-v7/README.md`。