# 股票信息助手 — 第一版（2026-07-12-v1）

基于 `stock-info.agent.md` 代理定义实现的中文前端 + FastAPI 后端。

## 功能
- **会话管理**：新建 / 切换 / 重命名 / 删除会话，消息持久化（SQLite）
- **上市详情**：按股票代码或名称查询上市板块、所属行业、主营业务、上市日期
- **历史行情**：指定时间段内的开盘价、收盘价、最高价、最低价、成交量
- **K 线可视化**：ECharts 蜡烛图 + 成交量
- **来源标注**：每条数据标注来源（AKShare）

## 取数方式（对应代理定义）
- 上市详情：AKShare `stock_profile_cninfo`（巨潮资讯网 cninfo，官方披露数据，含板块/行业/主营业务/上市日期）
- 历史行情：AKShare `stock_zh_a_daily`（新浪财经日线，含开/收/最高/最低/成交量）
- 说明：东方财富 `push2` 系列接口在当前网络环境下被代理拦截，故改用可达的 cninfo / 新浪源；公开财经网站检索（方式二兜底）本版暂未接入，后续可补 `web` 抓取

## 运行
```bash
pip install -r requirements.txt
uvicorn main:app --reload
# 浏览器打开 http://127.0.0.1:8000
```

## 目录结构
```
2026-07-12-v1/
├── main.py            # FastAPI 接口 + 静态托管
├── session_store.py   # SQLite 会话持久化
├── agent_runner.py    # 代理逻辑：代码识别 + AKShare 取数
├── requirements.txt
├── README.md
└── static/
    ├── index.html
    ├── app.js
    └── style.css
```

## 已知限制 / 下一步
- 自然语言理解为关键词启发式，可接入 LLM 让对话更自然
- 网站兜底（新浪/东方财富网页检索）尚未实现
- 缺少自选股、导出、流式输出
- 东方财富 `push2` 接口在本机被代理拦截，已改用 cninfo / 新浪源
