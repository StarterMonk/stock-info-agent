# 🦾 Stock-Info-Agent v7 — OpenRouter LLM · 价格预测引擎

### A 股对话式 Agent 的旗舰版本：任意 OpenAI 系模型 + 11 工具 + SARIMA 预测 + ECharts 可视化

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-teal?logo=fastapi&logoColor=white)
![OpenRouter](https://img.shields.io/badge/LLM-OpenRouter-orange)
![AKShare](https://img.shields.io/badge/AKShare-1.14%2B-green)
![SARIMA](https://img.shields.io/badge/预测-SARIMA%20%2B%20置信带-purple)
![Release](https://img.shields.io/github/v/release/StarterMonk/stock-info-agent?color=blue)

---

## 🇨🇳 第一部分 · 中文

### 这是什么？

**对话式 A 股智能体 v7**：用自然语言查询行情、财报、资金流，并调用「价格预测引擎」给出带置信区间的未来走势研判。

```text
「预测一下 600519 未来 10 个交易日的走势」
→ 工具调用 get_price_prediction
→ 方向偏多（概率 0.59）· 支撑 1151 · 压力 1363
→ 中位价 + 置信区间预测带图表 📈
```

> v7 是核心版本：其余 v1~v6 为演进史。v7 将 LLM 接入统一为 **OpenRouter REST**（OpenAI 兼容格式），
> 任何模型 ID 均可即插即用（含免费模型），不绑定任何厂商 SDK。

### ✨ 特性亮点

| 能力 | 说明 |
|------|------|
| 🧠 **LLM 自由选择** | `OPENROUTER_MODEL` 一行切换任意模型；实测 `openai/gpt-oss-20b:free` 免费可用且完整支持工具调用 |
| 🤖 **原生工具调用环路** | 手写 Agent 闭环（≤6 轮），消息采用 OpenAI `tool_calls` 格式；不依赖 LangGraph，仅需 `requests` |
| 🔧 **11 个专业工具** | 公司资料 / 历史行情 / 分时 / 财务三表 / 分红 / 资金流 / 常用指标 / 关键指标 / 机构预测 / 技术指标 / 价格预测 |
| 🔮 **价格预测引擎** | SARIMA(1,1,1) 中位价 + EMA 基线兜底 + 滚动波动率置信带（1.96σ√h）；walk-forward 回测门禁 ≥55% 且跑赢随机游走 5% |
| 📊 **技术指标库** | MA/MACD/RSI/KDJ/BOLL/ATR 等 20+ 指标与多空状态快照 |
| 📈 **ECharts 可视化** | 预测「中位价 + 置信区间 + 支撑/压力」区间带、分时图、K 线 |
| ⚡ **SSE 流式对话** | 工具步骤、逐段回复实时推送（浏览器 EventSource） |
| 🧠 **双级记忆** | 短期会话上下文（SQLite）+ 长期跨会话事实沉淀 |
| 🛡️ **稳健降级** | LLM 异常/限流 → 自动关键词模式，11 个工具照常可用 |
| 🗓️ **每日自动同步** | 15:30 增量同步日线 → `daily_price_history`；预测留痕 → `prediction_history` |

### 🚀 快速开始

```bash
# 1. 依赖（核心：requests / fastapi / uvicorn / akshare；statsmodels 用于预测引擎）
pip install -r requirements.txt

# 2. 配置
cp .env.example .env          # Windows: copy .env.example .env
```

`.env`（两行为全部配置，其余可选）：

```ini
OPENROUTER_API_KEY="sk-or-v1-..."        # 必填；不填则自动降级为关键词模式
OPENROUTER_MODEL="openai/gpt-oss-20b:free"  # 已实测可用；也可用付费模型提升质量
```

```bash
# 3. 启动
uvicorn main:app --port 8004
```

浏览器打开 **http://127.0.0.1:8004** 开聊。

> 💡 免费模型受 OpenRouter「数据政策 / 隐私限制」约束：若返回 404
> `No endpoints available matching your guardrail restrictions`
> 请在 `https://openrouter.ai/settings/privacy` 放开策略，或换其他模型。

### 🏗️ 架构

```text
浏览器 (ECharts) ⇄ FastAPI / SSE ⇄ Agent 闭环（工具调用 ≤6 轮）
     │                              ├─ llm_client → OpenRouter REST
     │                              ├─ tools.py → AKShare（11 工具，带超时缓存）
     │                              └─ memory（短期会话 / 长期事实）
     ▼
价格预测引擎：models.py (SARIMA+EMA+置信带) · features.py (20+ 指标)
     ▼
数据层：data_layer.py → daily_price_history / prediction_history
```

### 🔌 API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | JSON 对话（reply / tool_calls / chart） |
| GET / POST | `/api/chat/stream` | SSE 流式对话（浏览器 EventSource 走 GET） |
| GET | `/api/predict/{code}?horizon=10` | 预测直连 REST（不经 LLM） |
| GET/POST | `/api/sessions` | 会话列表 / 新建会话 |
| GET | `/api/sessions/{sid}/messages` | 会话消息 |
| GET | `/api/sessions/{sid}/export?fmt=md/json` | 导出会话 |
| DELETE | `/api/sessions/{sid}` | 删除会话 |

### 🔐 安全说明

- 密钥仅存于本地 `.env`（已 .gitignore，绝不入库）；发布包 zip **不含任何密钥/数据库/日志**
- 数据表命名一律英文全称：`daily_price_history`、`prediction_history`
- 所有远程数据接口均带超时与结果缓存，避免长阻塞

### ⚠️ 免责声明

> 仅供学习与研究，不构成投资建议。预测基于历史行情统计推断，股市有风险，决策需谨慎。

---

## 🇺🇸 Part 2 · English

### About

**v7** is the flagship version of Stock-Info-Agent — a conversational A-share assistant that couples **any OpenAI-compatible LLM via OpenRouter** with a **statistical price-forecasting engine**. Ask in plain language; get real market data, structured analysis and interactive charts.

### Why v7?

- **Vendor-free LLM**: one REST adapter (`requests` only), switch models by editing one env var — free models included.
- **Native tool-calling loop**: hand-written ≤6-round loop with OpenAI `tool_calls` format; no framework dependency.
- **Predictive analytics**: SARIMA + EMA baseline + volatility confidence bands, gated by walk-forward backtests.
- **Rock-solid fallback**: keyword mode keeps all 11 tools alive even if the LLM API is down.

### Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env      # fill OPENROUTER_API_KEY
uvicorn main:app --port 8004
```

Then open http://127.0.0.1:8004 — or hit the REST endpoints (`/api/chat`, `/api/predict/{code}`).

### Data Model

| Table | Purpose |
|-------|---------|
| `daily_price_history` | qfq daily bars (3y backfill, then daily 15:30 incremental syncs) |
| `prediction_history` | audit trail of every forecast |

### Disclaimer

Educational & research use only — not financial advice.

---

> 仓库总览（含 v1~v6 演进记录）见上级目录 `README.md`。