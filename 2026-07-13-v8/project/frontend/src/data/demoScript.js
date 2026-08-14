// 演示模式预录脚本：600519 贵州茅台 的"预测"请求完美回放。
// 数据由确定性伪随机游走生成（种子固定），保证每次录屏一致、离线可跑。
// 事件格式与 SSE 完全一致：{ type, data }，play() 同时支持字符串与对象。

function seeded(seed) {
  let s = seed
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296
    return s / 4294967296
  }
}

function genDates(n) {
  const out = []
  const d = new Date()
  d.setDate(d.getDate() - 1)
  while (out.length < n) {
    const day = d.getDay()
    if (day !== 0 && day !== 6) out.unshift(d.toISOString().slice(0, 10).replace(/-/g, ''))
    d.setDate(d.getDate() - 1)
  }
  return out
}

function buildMarketData() {
  const rand = seeded(600519)
  const dates = genDates(80)
  let price = 1320
  const closes = []
  const opens = []
  const highs = []
  const lows = []
  const vols = []
  for (let i = 0; i < dates.length; i++) {
    const drift = (rand() - 0.48) * 18
    const open = price + (rand() - 0.5) * 8
    price = Math.max(1200, open + drift)
    const close = price
    const high = Math.max(open, close) + rand() * 10
    const low = Math.min(open, close) - rand() * 10
    opens.push(+open.toFixed(2))
    closes.push(+close.toFixed(2))
    highs.push(+high.toFixed(2))
    lows.push(+Math.max(low, 1100).toFixed(2))
    vols.push(Math.round(2000000 + rand() * 1500000))
  }
  const ma = (w) =>
    closes.map((_, i) =>
      i < w - 1 ? null : +(closes.slice(i - w + 1, i + 1).reduce((a, b) => a + b, 0) / w).toFixed(2)
    )
  return {
    dates,
    kline: closes.map((c, i) => [opens[i], c, lows[i], highs[i]]),
    ma5: ma(5),
    ma10: ma(10),
    ma20: ma(20),
    vols,
    last: closes[closes.length - 1],
  }
}

const M = buildMarketData()
const ma5last = M.ma5[M.ma5.length - 1]
const ma20last = M.ma20[M.ma20.length - 1]

const candlestickChart = {
  type: 'candlestick',
  title: '贵州茅台（600519）K线图',
  x_axis: M.dates,
  series: [
    { name: 'K线', type: 'candlestick', data: M.kline },
    { name: 'MA5', type: 'line', data: M.ma5, lineStyle: { width: 1 }, itemStyle: { color: '#ff6600' } },
    { name: 'MA10', type: 'line', data: M.ma10, lineStyle: { width: 1 }, itemStyle: { color: '#22d3ee' } },
    { name: 'MA20', type: 'line', data: M.ma20, lineStyle: { width: 1 }, itemStyle: { color: '#a855f7' } },
    { name: '成交量', type: 'bar', data: M.vols, yAxisIndex: 1 },
  ],
  indicators: { 最新收盘: M.last, MA5: ma5last, MA20: ma20last },
}

const predictionChart = {
  type: 'prediction',
  title: '贵州茅台（600519）价格预测',
  x_axis: ['T+5', 'T+10', 'T+20'],
  series: [
    { name: '中位预测', type: 'line', data: [1361.8, 1368.31, 1381.33], lineStyle: { width: 2, color: '#6366f1' } },
    { name: '置信上界', type: 'line', data: [1376.5, 1392.1, 1418.7], lineStyle: { width: 1, type: 'dashed', color: '#10b981' } },
    { name: '置信下界', type: 'line', data: [1347.1, 1344.5, 1343.9], lineStyle: { width: 1, type: 'dashed', color: '#e6545a' } },
  ],
  indicators: { 当前价格: M.last, 方向: '偏多', 上涨概率: 0.956, 支撑位: 1151.01, 压力位: 1363.35 },
}

const technicalChart = {
  type: 'technical',
  title: '贵州茅台（600519）技术指标',
  x_axis: M.dates,
  series: [
    { name: '收盘价', type: 'line', data: M.kline.map((k) => k[1]), lineStyle: { width: 1.5, color: '#22d3ee' } },
    { name: 'MACD柱', type: 'bar', data: M.kline.map((_, i) => (i % 7 === 0 ? 0.4 : i % 5 === 0 ? -0.3 : 0.1)) },
  ],
  indicators: { 趋势: '多头', RSI: 52.3, MACD: '金叉', KDJ_K: 54.2 },
}

const replyChunks = [
  '### 公司概况',
  '**贵州茅台（600519）**',
  '- 板块：白酒',
  '- 行业：食品饮料',
  '- 主营：茅台酒系列产品的生产与销售',
  '',
  '### 行情数据',
  `共 80 个交易日，最新收盘 **${M.last}**`,
  `- 5 日均线 ${ma5last} / 20 日均线 ${ma20last}`,
  '- 成交量温和放大，价在均线上方运行',
  '',
  '### 技术分析',
  '- 趋势：多头（收盘价 > MA20 > MA60，均线向上）',
  '- MACD：金叉，红柱延续',
  '- RSI(14)：52.3（未超买）',
  '- KDJ：K=54.2，D=48.7',
  '- 支撑位 1151.01 / 压力位 1363.35',
  '',
  '### 价格预测',
  '- 方向：偏多（上涨概率 0.956）',
  '- 方法：简单方法集成（simple 级别）',
  '- 支撑位 1151.01 / 压力位 1363.35',
  '  - T+5：**1361.8** 元',
  '  - T+10：**1368.31** 元',
  '  - T+20：**1381.33** 元',
  '',
  '> 预测基于历史统计推断，不构成投资建议。',
]

export const demoScript = [
  { type: 'start', data: '正在启动多智能体分析……' },
  { type: 'tool', data: { name: 'get_profile', args: { code: '600519' }, result_summary: '成功' } },
  { type: 'tool', data: { name: 'get_history', args: { code: '600519' }, result_summary: '成功，80 条' } },
  { type: 'tool', data: { name: 'get_price_prediction', args: { code: '600519' }, result_summary: '成功' } },
  { type: 'chart', data: candlestickChart },
  { type: 'chart', data: predictionChart },
  { type: 'chart', data: technicalChart },
  ...replyChunks.map((c) => ({ type: 'chunk', data: c })),
  { type: 'done', data: '完成' },
]
