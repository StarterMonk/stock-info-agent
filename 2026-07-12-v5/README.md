# v5 — LangGraph 编排的股票信息助手

这是 `2026-07-11-Stock-Collector` 项目的第 5 个版本。它在 v4（手写工具调用循环）的基础上，把 Agent 的编排换成 [LangGraph](https://github.com/langchain-ai/langgraph) 的 `StateGraph`，图结构更清晰、好调试、易扩展。

> 练手项目，边学边做，欢迎拍砖 🙏

---

## 1. 整体架构（分层）

```mermaid
flowchart TB
    subgraph FE["前端 (static/)"]
        UI["index.html + app.js<br/>ECharts K线 / SSE 流式渲染"]
    end

    subgraph API["FastAPI 层 (main.py :8004)"]
        ROUTES["/api/chat · /api/chat/stream<br/>/api/sessions · /api/sessions/export"]
    end

    subgraph AGENT["Agent 编排层 (graph_agent.py)"]
        GRAPH["LangGraph StateGraph<br/>agent → tools → memory"]
        MEM["MemorySaver<br/>(短期记忆 checkpointer)"]
    end

    subgraph TOOLS["工具层 (tools.py, 9 个 @tool)"]
        T1["get_profile"] & T2["get_history"] & T3["get_intraday"]
        T4["get_financials"] & T5["get_dividend"] & T6["get_capital_flow ⚠️"]
        T7["get_indicators"] & T8["get_key_metrics"] & T9["get_forecast"]
    end

    subgraph EXT["外部依赖"]
        LLM["Gemini/Gemma<br/>(ChatGoogleGenerativeAI)"]
        AK["AKShare 多源数据"]
        DB[("SQLite<br/>sessions / messages / long_memory")]
    end

    UI -- "HTTP / SSE" --> ROUTES
    ROUTES --> GRAPH
    GRAPH <--> MEM
    GRAPH --> LLM
    GRAPH --> TOOLS
    TOOLS --> AK
    ROUTES --> DB
    GRAPH --> DB
```

---

## 2. LangGraph 状态图（核心）

这是 v5 与 v4 最大的区别——v4 是手写 `for` 循环，v5 是**声明式图**：

```mermaid
stateDiagram-v2
    [*] --> agent

    agent --> tools: 最后一条消息<br/>含 tool_calls
    agent --> memory: 无 tool_calls<br/>(已得到最终回答)

    tools --> agent: 执行完工具<br/>追加 ToolMessage

    memory --> [*]: 抽取本轮事实<br/>写入长期记忆

    note right of agent
        ChatGoogleGenerativeAI
        + bind_tools(TOOLS)
        注入 system 提示 + 长期记忆
        产出 AIMessage
    end note

    note right of tools
        LangGraph 预置 ToolNode
        自动配对 tool_call_id
        产出 ToolMessage
    end note

    note right of memory
        复用 v4 memory_store
        合并进 long_memory 表
    end note
```

条件边 `_should_continue` 的逻辑（在 `graph_agent.py` 中）：

```python
def _should_continue(state):
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "tools"      # 还要继续调工具
    return "memory"         # 收尾：写长期记忆
```

---

## 3. 一次对话的生命周期

```mermaid
sequenceDiagram
    participant U as 用户
    participant API as main.py
    participant G as StateGraph
    participant A as agent节点
    participant L as Gemini LLM
    participant T as tools节点
    participant M as memory节点
    participant DB as SQLite

    U->>API: POST /api/chat {session_id, message}
    API->>G: invoke({messages:[Human], session_id})
    Note over G: thread_id=session_id<br/>短期记忆从 MemorySaver 取回
    G->>A: 注入 system+长期记忆
    A->>L: 带 tools 的提问
    L-->>A: AIMessage(tool_calls=[get_history])
    A->>T: 执行工具
    T->>T: 调 tools.py → AKShare
    T-->>A: ToolMessage(结果)
    A->>L: 带上工具结果再问
    L-->>A: AIMessage(纯文本回答)
    A->>M: 无 tool_calls → 进入 memory
    M->>DB: 抽取事实 → 更新 long_memory
    G-->>API: {reply, tool_calls, chart}
    API->>DB: 存 user/assistant 消息
    API-->>U: ChatResponse
```

---

## 4. 文件职责对照

| 文件 | v5 职责 | 与 v4 关系 |
|------|---------|-----------|
| `graph_agent.py` | **新增**：LangGraph 图编排（agent/tools/memory 三节点） | v4 的 `agent_runner.py` 被取代 |
| `main.py` | FastAPI 入口，端口 8004，调用 `graph_app.invoke(...)` | 结构同 v4，仅换调用入口 |
| `tools.py` | 9 个工具函数（被 `@tool` 包装） | 完全复用 v4 |
| `llm_client.py` | Gemini REST 接入（降级用） | 完全复用 v4 |
| `memory_store.py` | 长期记忆持久化 | 完全复用 v4 |
| `session_store.py` | 会话/消息存储 | 完全复用 v4 |
| `static/` | 前端页面 | 完全复用 v4 |

---

## 5. v4 → v5 关键变化

```mermaid
flowchart LR
    subgraph V4["v4 手写循环"]
        L1["for _ in range(5):<br/>generate() → 解析 functionCall<br/>→ call_tool() → 拼 functionResponse<br/>→ 再 generate()"]
    end
    subgraph V5["v5 LangGraph"]
        L2["StateGraph 声明节点<br/>ToolNode 自动配对<br/>MemorySaver 管短期记忆"]
    end
    V4 -->|"更清晰 / 好调试 / 易扩展"| V5
```

要点：
- **短期记忆**：v4 手动从 `messages` 表读最近 12 轮拼 `contents`；v5 交给 `MemorySaver` checkpointer（`thread_id = session_id`），图自动维护。
- **工具调用闭环**：v4 自己解析 `functionCall` / 拼 `functionResponse`；v5 用 `ToolNode` 自动处理 `tool_call_id ↔ ToolMessage` 配对。
- **长期记忆**：两者都复用 `memory_store`，但 v5 把它做成图的 `memory` 节点，在对话自然结束时触发。
- **降级路径**：无 `GEMINI_API_KEY` 时，v5 仍走 v4 同款关键词降级（`_fallback_run`），且依赖缺失也能正常导入模块。

---

## 6. 快速开始

```bash
cd 2026-07-12-v5
source ../2026-07-12-v1/.venv/bin/activate   # 复用 v1 的虚拟环境
pip install -r requirements.txt
export GEMINI_API_KEY="你的Key"               # 可选，留空则降级关键词驱动
uvicorn main:app --port 8004
```

浏览器打开 http://127.0.0.1:8004

> 小提示：不填 `GEMINI_API_KEY` 也能跑，只是会退化成「关键词驱动」的简化模式，用来体验流程完全够用。

---

## 已知限制

- 我这台机器网络下，东方财富 push2 行情接口被代理拦了，`get_capital_flow`（个股资金流向）暂时用不了；按需求把 API 调用位置先留空，并给了替代方案（北向/板块资金流）。
- LLM 工具调用闭环需要配置 `GEMINI_API_KEY`；没配的话走关键词降级路径（已验证可用）。

## 许可证

MIT（如需商用请自行确认数据源合规）。
