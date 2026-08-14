# 🦾 Stock-Info-Agent v8 — Vue3 现代前端

### LLM 对话 · 分类回答 · 算法选择 · 动画图表工作台

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Vue3](https://img.shields.io/badge/Vue-3.4-brightgreen?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-teal?logo=fastapi&logoColor=white)
![OpenRouter](https://img.shields.io/badge/LLM-OpenRouter-orange)
![ECharts](https://img.shields.io/badge/ECharts-5.5-purple)
![ZeroBuild](https://img.shields.io/badge/零构建-CDN-yellow)

---

## 🇨🇳 v8 是什么？

v8 是 **A 股智能助手的全新前端版本**：后端沿用 v7（OpenRouter LLM + 价格预测引擎），
前端以 **Vue 3（CDN 零构建）** 重写，主打**现代简洁**的交互体验。

```
「分析 600519」
→ 弹出算法选择卡（MA5 / MA20 / MA5+线性回归 / EMA / BOLL / SARIMA）
→ 选择算法 → 后端计算 → 图表工作台（K线/折线/柱状/面积，带过渡动画切换）
```

### ✨ 核心特性

| 特性 | 说明 |
|------|------|
| 🎨 **现代简洁设计** | 浅/深双主题、毛玻璃弹窗、圆角卡片、柔和阴影，CSS 变量驱动 |
| ✨ **按键过渡动画** | 按钮按压缩放、图标旋转、消息错峰入场、会话弹出动画 |
| 🗂️ **回答分类展现** | Agent 回复按 `行情 / 财务 / 预测 / 分析 / 概况 / 回答` 分块呈现，各自着色与入场动画 |
| 🧮 **算法选择机制** | 用户提出数据分析需求时，自动弹出算法选择卡（单项选择、卡片动效），再执行分析 |
| 📊 **图表工作台** | 同一份数据支持 K线 / 折线 / 柱状（涨跌幅）/ 面积 四种视图，切换带缩放淡入动画；叠加线可点击开关 |
| ⚡ **SSE 流式对话** | 工具调用 step 与回复逐段推送 |
| 🌗 **主题记忆** | 深浅主题切换持久化，图表即时响应配色 |

### 🚀 快速开始

```bash
# 1.（可选）配置密钥
copy .env.example .env    # 填入 OPENROUTER_API_KEY；不填则自动降级关键词模式

# 2. 启动（零构建：前端即 static/ 下的 Vue 单页，无需 Node/npm）
pip install -r requirements.txt
uvicorn main:app --port 8008
```

浏览器打开 **http://127.0.0.1:8008**

```
试试：
· 分析 600519                       → 弹出算法选择 → 图表工作台
· 预测一下 601318 未来 10 日        → 预测分类块 + 置信带图
· 查询 000001 的资金流              → 分析分类块
· 长安汽车属于什么板块              → 概况分类块
```

## 算法池（/api/analysis/*）

| key | 算法 | 输出 |
|-----|------|------|
| ma | MA 移动平均线 | MA5 + MA20 叠加线、金叉/死叉结论 |
| ma_reg | MA5 + 线性回归 | MA5 + 最小二乘趋势线、60 日斜率 |
| ema | EMA 指数均线 | EMA12/26 + MACD 柱 |
| boll | BOLL 布林带 | 上/中/下轨 +/-2sigma、超买超卖判定 |
| sarima | SARIMA 预测 | 未来 10 日中位价与置信带（预测引擎） |

接口：GET /api/analysis/options（算法清单）· POST /api/analysis/run（执行 {code, algorithm}）

## 文件结构

2026-07-13-v8/
  static/            Vue3 前端（零构建，CDN）
    index.html       单页骨架
    app.js           Vue 应用：SSE / 分类 / 算法选择 / 图表
    style.css        现代简洁主题 + 全套过渡动画
  analysis.py        新增：算法池分析引擎
  main.py            FastAPI（新增分析接口，端口 8008）
  其余 py 与 v7 一致：llm_client / graph_agent / tools / data_layer / models ...

## 与 v7 的关系

| 维度 | v7 | v8 |
|------|----|----|
| 前端 | 原生 JS 单页 | Vue 3（CDN 零构建），分类回答 + 动效 |
| 数据分析 | 无（仅预测） | 算法选择 + 图表工作台 |
| 端口 | 8004 | 8008 |
| API 新增 | — | /api/analysis/options · /api/analysis/run |

> 免责声明：仅学习与研究用途，不构成投资建议。股市有风险，决策需谨慎。

---

## English

**v8** re-imagines the Stock-Info-Agent frontend with **Vue 3 (zero-build, CDN)** on top of the v7 backend (OpenRouter LLM + prediction engine).

- Modern minimal UI: light/dark themes, glass modals, rounded cards, CSS-variable driven
- Micro-animations on every interaction: button press scale, staggered message entrance, animated tabs
- Categorized answers into Quote / Finance / Forecast / Analysis / Profile blocks
- Algorithm picker: typing an analysis request opens a selectable card list (MA5, MA20, MA5+Linear Regression, EMA, BOLL, SARIMA)
- Chart workbench: candlestick / line / bar / area views with animated switching and toggleable overlays
- Runs with zero build steps — no Node, no bundler

