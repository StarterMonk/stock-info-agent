# Stock Agent v9 — 前端开发文档

## 1. 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    浏览器 (Vue3 + ECharts)               │
│  index.html / app.js / style.css                        │
│  EventSource → SSE → 分类渲染 → 图表 Dock                │
└──────────────────────┬──────────────────────────────────┘
                       │ GET /api/chat/multi?session_id=&message=
                       │ EventSource (SSE)
┌──────────────────────▼──────────────────────────────────┐
│               FastAPI (project/backend/main.py)          │
│  _multi_agent_stream() → graph.invoke() → SSE events    │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│            LangGraph StateGraph (agent_core/)            │
│                                                         │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐            │
│  │ Supervisor│──▶│ Agent A  │──▶│ Agent C  │──┐         │
│  │ (LLM路由) │   │ (数据获取)│   │ (数据处理)│  │         │
│  └──────────┘   └──────────┘   └────┬─────┘  │         │
│       │              ▲               │        │         │
│       │              └───────────────┘        │         │
│       │            C→A 数据回路                │         │
│       │                                       ▼         │
│       │              ┌──────────┐   ┌──────────┐        │
│       └─────────────▶│ Assembler│◀──│ Agent B  │        │
│                      │ (组装回复)│   │ (图表生成)│        │
│                      └──────────┘   └──────────┘        │
└─────────────────────────────────────────────────────────┘
```

---

## 2. SSE 事件协议

浏览器通过 `EventSource` 连接 `GET /api/chat/multi`，服务端推送以下事件：

### 2.1 事件类型

| 事件 | data 格式 | 说明 |
|------|-----------|------|
| `start` | `"正在启动多智能体分析……"` | 流开始 |
| `agent` | `{"agent":"A","action":"fetch"}` | 智能体执行通知 |
| `tool` | `{"name":"get_history","args":{...},"result_summary":"成功，200 条"}` | 工具调用结果 |
| `chunk` | `"### 公司概况"` (一行文本) | 最终回复的逐行片段 |
| `chart` | `{"type":"candlestick","title":"...","x_axis":[...],"series":[...]}` | 图表渲染数据 |
| `anomaly` | `{"anomalies":[...],"question":"检测到数据异常"}` | 数据异常通知 |
| `data` | `{"tool_calls":[...],"chart":{}}` | 完整数据包（兼容旧版） |
| `done` | `"完成"` | 流结束 |

### 2.2 事件流顺序

```
start
  ├── agent (A: 数据获取)
  ├── tool  (get_profile)
  ├── tool  (get_history)
  ├── agent (C: 数据处理)        ← 仅 needs_processing=true
  ├── agent (B: 图表生成)        ← 仅 needs_chart=true
  ├── chart (candlestick)        ← 0~N 个图表事件
  ├── chart (technical)
  ├── chunk (第一行回复)
  ├── chunk (第二行回复)
  ├── ...
  ├── data  (完整 tool_calls + chart)
  └── done
```

### 2.3 异常事件（可选）

当 Agent C 检测到数据异常且未自动解决时：
```
anomaly → {"anomalies": [...], "question": "请选择处理方式"}
```
前端需弹窗让用户选择，然后 POST `/api/anomaly/resolve`。

---

## 3. 图表数据格式（Agent B 输出）

Agent B 生成的图表是纯数据（无 HTML），前端用 ECharts 渲染。

### 3.1 K线图 (candlestick)

```json
{
  "type": "candlestick",
  "title": "贵州茅台（600519）K线图",
  "x_axis": ["20251021", "20251022", ...],
  "series": [
    {"name": "K线", "type": "candlestick", "data": [[open, close, low, high], ...]},
    {"name": "MA5", "type": "line", "data": [null, null, ..., 1455.87, ...], "lineStyle": {"width": 1}, "itemStyle": {"color": "#ff6600"}},
    {"name": "MA10", "type": "line", "data": [...]},
    {"name": "MA20", "type": "line", "data": [...]},
    {"name": "成交量", "type": "bar", "data": [2544267, ...], "yAxisIndex": 1}
  ],
  "annotations": [{"name": "MA5", "value": 1340.57}],
  "indicators": {"最新收盘": 1355.29, "MA5": 1340.57, "MA20": 1321.55}
}
```

**ECharts 渲染要点：**
- 双 Y 轴：主图（价格）+ 副图（成交量）
- K线 data 格式：`[open, close, low, high]`（ECharts 专用顺序）
- MA 线前 N 个为 `null`（窗口期无值）
- 需要 `dataZoom` 支持缩放（默认显示最近 60 天）

### 3.2 预测图 (prediction)

```json
{
  "type": "prediction",
  "title": "贵州茅台（600519）价格预测",
  "x_axis": ["T+5", "T+10", "T+20"],
  "series": [
    {"name": "中位预测", "type": "line", "data": [1361.8, 1368.31, 1381.33], "lineStyle": {"width": 2, "color": "#6366f1"}},
    {"name": "置信上界", "type": "line", "data": [...], "lineStyle": {"width": 1, "type": "dashed", "color": "#10b981"}},
    {"name": "置信下界", "type": "line", "data": [...], "lineStyle": {"width": 1, "type": "dashed", "color": "#e6545a"}}
  ],
  "annotations": [{"name": "支撑位", "value": 1151.01}, {"name": "压力位", "value": 1363.35}],
  "indicators": {"当前价格": 1355.29, "方向": "偏多", "上涨概率": 0.956, "支撑位": 1151.01, "压力位": 1363.35}
}
```

### 3.3 技术指标图 (technical)

```json
{
  "type": "technical",
  "title": "贵州茅台（600519）技术指标",
  "x_axis": ["20251021", ...],
  "series": [
    {"name": "收盘价", "type": "line", "data": [1462.26, ...], "lineStyle": {"width": 1.5}},
    {"name": "MACD柱", "type": "bar", "data": [0.0, -0.454, ...], "yAxisIndex": 1}
  ],
  "annotations": [{"name": "RSI", "value": 45.2}, {"name": "MACD", "value": "金叉"}],
  "indicators": {"趋势": "多头", "RSI": 45.2, "MACD": "金叉", "KDJ-K": 52.1}
}
```

---

## 4. 分类回复格式（Assembler 输出）

Assembler 将各智能体输出组装为带 `###` 头的结构化文本，前端 `categorize()` 按头拆分到 tab。

### 4.1 输出格式

```
### 公司概况
**贵州茅台（600519）**
- 板块：白酒
- 行业：食品饮料
- 主营：茅台酒系列产品的生产与销售

### 行情数据
共 200 个交易日，最新收盘 **1355.29**
- 开盘 1338.0 / 最高 1359.6 / 最低 1337.0
- 成交量 3235348.0

### 技术分析
- 趋势：多头
- MACD：金叉
- RSI(14)：52.3
- 支撑位 1151.01 / 压力位 1363.35

### 价格预测
- 方向：偏多（上涨概率 0.956）
- 方法：简单方法集成（simple级别）
- 支撑位 1151.01 / 压力位 1363.35
  - T+5：**1361.8** 元
  - T+10：**1368.31** 元
  - T+20：**1381.33** 元
```

### 4.2 分类映射

| `###` 头 | 分类 key | 图标 | 说明 |
|-----------|----------|------|------|
| `### 公司概况` | `info` | 🏢 | 公司基本信息 |
| `### 行情数据` | `quote` | 📊 | K线/行情数据 |
| `### 技术分析` | `analysis` | 🧮 | MACD/RSI/趋势 |
| `### 价格预测` | `forecast` | 🔮 | 预测结果 |
| `### 财务数据` | `finance` | 💰 | 财务指标 |
| `### 公告与预告` | `finance` | 💰 | 公告信息 |

前端 `categorize(m)` 函数按 `###` 分割文本，用关键词匹配分类。

---

## 5. API 端点清单

### 5.1 核心对话

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/chat/multi?session_id=&message=` | **主端点** — SSE 多智能体对话 |
| `POST` | `/api/chat/multi` | 同上（POST 版本，body: `{session_id, message}`） |
| `POST` | `/api/anomaly/resolve` | 异常处理 `{session_id, anomaly_id, resolution}` |

### 5.2 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/sessions` | 列出所有会话 `[{id, title, created_at}]` |
| `POST` | `/api/sessions` | 创建新会话 |
| `GET` | `/api/sessions/{sid}/messages` | 获取会话消息 `[{role, content, created_at}]` |
| `PUT` | `/api/sessions/{sid}` | 重命名 `{title}` |
| `DELETE` | `/api/sessions/{sid}` | 删除会话 |
| `GET` | `/api/sessions/{sid}/export?fmt=markdown` | 导出会话 |

### 5.3 辅助

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/llm-status` | LLM 连通性检查 |
| `GET` | `/api/stocks/search?q=` | 股票名称搜索 |
| `POST` | `/api/stocks/sync` | 手动同步股票名单 |
| `GET` | `/api/predict/{code}?horizon=10` | 直接预测（不经 LLM） |
| `GET` | `/api/analysis/options` | 算法列表 |
| `POST` | `/api/analysis/run` | 运行分析算法 |

---

## 6. 前端状态管理

### 6.1 Vue data 字段

```javascript
{
  // 会话
  sessions: [],           // [{id, title, created_at}]
  currentId: null,        // 当前会话 ID
  messages: [],           // [{id, role, text, chips, cats, analysis, charts}]

  // 输入
  input: "",              // 用户输入
  thinking: false,        // 正在处理中

  // LLM 状态
  online: false,
  llmStatus: "checking",  // "checking" | "online" | "offline"

  // 多智能体
  agentProgress: { A: false, B: false, C: false },
  lastChart: null,        // 最新图表数据
  showChartDock: false,   // 图表 Dock 显示

  // 异常处理
  anomalyModal: { show: false, anomalies: [], question: "" },

  // 图表 Dock
  dockWidth: 420,
  dockDragging: false,
}
```

### 6.2 消息数据结构

```javascript
{
  id: "a-1723651234567",
  role: "assistant",       // "user" | "assistant"
  text: "### 公司概况\n...",  // 原始回复文本
  chips: [                 // 工具调用徽章
    { name: "get_history", icon: "📜", status: "成功，200 条" }
  ],
  cats: [                  // 分类结果（done 事件后生成）
    { key: "info", label: "概况", icon: "🏢", text: "..." },
    { key: "quote", label: "行情", icon: "📊", text: "..." },
  ],
  analysis: null,          // 算法分析结果（旧版）
  charts: [                // 图表列表（chart 事件推入）
    { type: "candlestick", title: "...", x_axis: [...], series: [...] }
  ],
}
```

---

## 7. 前端核心逻辑

### 7.1 SSE 连接（send 方法）

```
用户输入 → 创建 assistantMsg → EventSource(/api/chat/multi)
  ├── on "tool"   → 推入 assistantMsg.chips
  ├── on "agent"  → 更新 agentProgress[A/B/C]
  ├── on "chart"  → 推入 assistantMsg.charts + 设置 lastChart
  ├── on "anomaly"→ 弹出 anomalyModal
  ├── on "chunk"  → 追加 assistantMsg.text
  ├── on "done"   → categorize(assistantMsg) → 关闭 ES
  └── onerror     → 关闭 ES, thinking=false
```

### 7.2 分类逻辑（categorize 方法）

```javascript
categorize(m) {
  // 1. 按 ### 分割文本为 sections
  // 2. 每个 section 用关键词匹配到分类桶
  // 3. 返回 [{key, label, icon, text}]
}
```

关键词映射：
- `info`: 公司/简介/主营/行业/板块/概况
- `quote`: 行情/涨跌/收盘/开盘/最高/最低/K线/走势
- `forecast`: 预测/预估/未来/趋势/上涨/下跌/方向/概率/支撑/压力
- `analysis`: 技术/指标/MACD/RSI/均线/布林/趋势/动量
- `finance`: 财务/营收/利润/净利/ROE/分红/股息

### 7.3 ECharts 渲染（renderChart 方法）

```javascript
renderChart() {
  // 1. 获取 chartContainer DOM
  // 2. echarts.init(container, theme)
  // 3. 根据 chart.type 构建 option
  // 4. chart.setOption(option)
}

_buildChartOption(cd) {
  switch(cd.type) {
    case "candlestick": return this._candlestickOption(...)
    case "prediction":  return this._predictionOption(...)
    case "technical":   return this._technicalOption(...)
  }
}
```

**K线图 option 结构：**
- 双 grid：主图 55% + 成交量 18%
- 双 xAxis：共享 category，主图带 label，副图隐藏
- dataZoom：inside + slider，默认显示最近 60 天

---

## 8. Agent 核心模块说明

### 8.1 文件结构

```
agent_core/
├── graph_state.py          # StockState TypedDict（共享状态定义）
├── graph_builder.py        # StateGraph 构建 + 路由逻辑 + assembler
├── agents/
│   ├── supervisor.py       # LLM 意图解析 + 路由决策
│   ├── agent_a_fetch.py    # AKShare 工具调用获取数据
│   ├── agent_b_chart.py    # ECharts 图表数据生成
│   └── agent_c_process.py  # 异常检测 + 模型预测 + LLM 验证
├── models_simple.py        # MA/EMA/BOLL/线性回归/季节分解
├── models_medium.py        # XGBoost/LightGBM/GARCH/Kalman/ARIMA
├── models_complex.py       # LSTM/Transformer
├── features.py             # 技术指标计算
├── data_layer.py           # SQLite 数据层
├── tools.py                # AKShare 工具函数封装
├── llm_client.py           # OpenRouter LLM 客户端
├── session_store.py        # 会话存储
├── memory_store.py         # 长期记忆
└── stock_search.py         # 股票名称检索
```

### 8.2 数据流

```
用户: "600519 预测"
       │
       ▼
Supervisor ──→ 解析意图: [prediction]
       │       复杂度: simple
       │       data_requests: [get_profile, get_history, get_price_prediction]
       ▼
Agent A ──→ 调用 AKShare
       │    raw_data = {get_profile: {...}, get_history: {...}, get_price_prediction: {...}}
       ▼
Agent C ──→ 异常检测 → 数据清洗 → 运行 simple 方法
       │    prediction = {direction: "偏多", forecasts: [...], ...}
       ▼
Agent B ──→ 生成图表数据
       │    charts = [candlestick, prediction, technical]
       ▼
Assembler ──→ 组装分类回复
       │    final_reply = "### 公司概况\n...\n### 行情数据\n...\n### 价格预测\n..."
       ▼
SSE 流 → 浏览器渲染
```

### 8.3 C→A 数据回路

当 Agent C 发现数据不足时（如历史数据少于所需天数）：

```
Agent C: needs_more_data=True, data_requests=[{tool:"get_history", args:{...}}]
    │
    ▼
Agent A: 合并新数据到 raw_data, needs_more_data=False
    │
    ▼
Agent C: 重试（c_retry_count=1），不再检查数据充足性，直接处理
```

防死循环：`c_retry_count` 上限为 1，异常处理节点自动应用默认策略。

---

## 9. 已知限制

1. **LLM 依赖**：Supervisor 依赖 OpenRouter 解析意图。LLM 不可用时，意图列表为空，但默认会获取 profile + history + 生成图表。
2. **预测图无置信区间**：中等/简单方法仅输出 median_price，无 low_price/high_price。预测图仅显示中位线。
3. **异常处理**：当前自动应用默认策略（forward_fill），无真正用户交互。`/api/anomaly/resolve` 端点仅返回 ok。
4. **图表 Dock**：无最小化/最大化，仅支持拖拽调整宽度。
5. **会话持久化**：SSE 流中消息存入 SQLite，但图表数据不持久化（刷新后丢失）。

---

## 10. 启动方式

```bash
cd project/backend
python -m uvicorn main:app --host 127.0.0.1 --port 8008 --reload
```

访问 `http://127.0.0.1:8008/`

### 环境变量 (.env)

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```
