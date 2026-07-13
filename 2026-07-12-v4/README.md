# 股票信息助手 v4（A 股）

在 v3 基础上新增两大能力：

## 新增特性
1. **Agent 多轮记忆**
   - 短期记忆：每轮从 `messages` 表读取最近 12 轮，作为 Gemini `contents` 传入，实现 stateful 多轮对话。
   - 长期记忆：每轮把工具结果摘要交给 LLM 抽取为稳定事实，持久化到 SQLite `long_memory` 表；下一轮注入 system 上下文，跨会话保持连贯。
2. **Agent 工具调用（Tool Calling）**
   - 覆盖目标股票的**全部 AKShare 信息维度**，由 LLM 自主决定调用哪些工具：
     - `get_profile` 公司资料/上市板块/主营业务 ✅
     - `get_history` 历史日 K 线 ✅
     - `get_intraday` 盘中分时 ✅
     - `get_financials` 三大财务报表 ✅
     - `get_dividend` 分红送配 ✅
     - `get_indicators` 估值与财务指标 ✅
     - `get_key_metrics` 主要财务摘要 ✅
     - `get_forecast` 业绩报告/预告 ✅
     - `get_capital_flow` 个股资金流向 ⚠️ 东方财富接口被本机代理拦截，按需求「API 位置先留空」，返回明确不可用说明 + 替代建议（联网检索确认）。
   - 前端实时展示工具调用进度（🔧 调用工具 … → 结果摘要）。

## 运行
```bash
source ../2026-07-12-v1/.venv/bin/activate
export GEMINI_API_KEY="你的Key"   # 可选；留空则降级为关键词驱动
export V4_DB_PATH="$(pwd)/v4_sessions.db"
uvicorn main:app --port 8003
```
打开 http://127.0.0.1:8003

## 文件
- `tools.py`：全维度工具函数 + functionDeclaration schema
- `agent_runner.py`：LLM 主导 + 工具调用闭环 + 多轮记忆
- `llm_client.py`：Gemini/Gemma 多轮 + function calling 接入
- `memory_store.py`：长期记忆抽取与持久化
- `main.py`：FastAPI 路由（会话/聊天/流式/导出）
- `static/`：中文前端（含工具进度、K线图）
