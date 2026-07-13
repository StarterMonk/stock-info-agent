# 股票信息助手 — 第二版（2026-07-12-v2）

在 v1 基础上新增：SSE 流式输出、会话导出、网站兜底检索（方式二）。

## 新增功能（相对 v1）
- **SSE 流式输出**：`POST /api/chat/stream` 逐段返回结果，前端用 EventSource 渲染，体验更流畅
- **会话导出**：`GET /api/sessions/{sid}/export?fmt=markdown|json` 导出为 Markdown 或 JSON，前端一键下载
- **网站兜底（方式二）**：当 AKShare 取数失败时，自动检索新浪财经 / 东方财富个股页补充信息（已修复中文编码）

## 取数方式（对应代理定义）
- 上市详情：AKShare `stock_profile_cninfo`（巨潮资讯网）
- 历史行情：AKShare `stock_zh_a_daily`（新浪财经日线）
- 网站兜底：新浪财经 / 东方财富网页检索（方式二，AKShare 失败时使用）

## 运行
```bash
# 复用 v1 的虚拟环境（已含全部依赖）
source ../2026-07-12-v1/.venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8001
# 浏览器打开 http://127.0.0.1:8001
```

## 目录结构
```
2026-07-12-v2/
├── main.py            # FastAPI 接口（含 SSE / 导出）+ 静态托管
├── session_store.py   # SQLite 会话持久化
├── agent_runner.py    # 代理逻辑：代码识别 + AKShare + 网站兜底
├── requirements.txt
├── README.md
└── static/
    ├── index.html     # 含导出按钮
    ├── app.js         # SSE 流式 + 导出
    └── style.css
```

## 已知限制 / 下一步
- 自然语言理解为关键词启发式，可接入 LLM 让对话更自然
- 网站兜底仅返回页面标题与链接，未做深度字段抽取
- 缺少自选股、流式输出中断恢复
