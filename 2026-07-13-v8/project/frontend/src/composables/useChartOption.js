// ECharts option 构造：消费后端 chart 事件数据，生成三类图。
// 类型：candlestick（K线+MA+成交量）、prediction（预测中位+上下界）、technical（收盘价+MACD）

const UP = '#ef5350'
const DOWN = '#26a69a'

function candlestickOption(cd) {
  const dates = cd.x_axis || []
  const series = cd.series || []
  const kline = series.find((s) => s.type === 'candlestick')
  const vol = series.find((s) => s.name && s.name.includes('成交量'))
  const mas = series.filter((s) => s.type === 'line')

  return {
    backgroundColor: 'transparent',
    animationDuration: 600,
    legend: {
      data: series.map((s) => s.name),
      textStyle: { color: '#aab4c8' },
      top: 0,
    },
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    grid: [
      { left: 56, right: 16, top: 36, height: '52%' },
      { left: 56, right: 16, top: '74%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: '#2a3550' } },
        axisLabel: { color: '#6b7793' },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: dates,
        boundaryGap: true,
        axisLine: { lineStyle: { color: '#2a3550' } },
        axisLabel: { show: false },
      },
    ],
    yAxis: [
      {
        scale: true,
        axisLine: { lineStyle: { color: '#2a3550' } },
        axisLabel: { color: '#6b7793' },
        splitLine: { lineStyle: { color: 'rgba(42,53,80,0.5)' } },
      },
      {
        gridIndex: 1,
        splitNumber: 2,
        axisLine: { lineStyle: { color: '#2a3550' } },
        axisLabel: { color: '#6b7793' },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      { type: 'inside', xAxisIndex: [0, 1], start: Math.max(0, dates.length - 60), end: 100 },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        start: Math.max(0, dates.length - 60),
        end: 100,
        bottom: 4,
        height: 16,
        borderColor: '#2a3550',
        textStyle: { color: '#6b7793' },
      },
    ],
    series: [
      {
        name: kline ? kline.name : 'K线',
        type: 'candlestick',
        data: kline ? kline.data : [],
        itemStyle: {
          color: UP,
          color0: DOWN,
          borderColor: UP,
          borderColor0: DOWN,
        },
      },
      ...mas.map((m) => ({
        name: m.name,
        type: 'line',
        data: m.data,
        smooth: true,
        showSymbol: false,
        lineStyle: m.lineStyle || { width: 1 },
        itemStyle: m.itemStyle || {},
      })),
      {
        name: vol ? vol.name : '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: vol ? vol.data : [],
        itemStyle: { color: '#3b82f6' },
      },
    ],
  }
}

function predictionOption(cd) {
  const dates = cd.x_axis || []
  const series = cd.series || []
  const mid = series.find((s) => s.name && s.name.includes('中位'))
  const up = series.find((s) => s.name && s.name.includes('上界'))
  const low = series.find((s) => s.name && s.name.includes('下界'))

  return {
    backgroundColor: 'transparent',
    legend: { data: series.map((s) => s.name), textStyle: { color: '#aab4c8' }, top: 0 },
    tooltip: { trigger: 'axis' },
    grid: { left: 56, right: 20, top: 36, bottom: 36 },
    xAxis: { type: 'category', data: dates, axisLine: { lineStyle: { color: '#2a3550' } }, axisLabel: { color: '#6b7793' } },
    yAxis: { scale: true, axisLine: { lineStyle: { color: '#2a3550' } }, axisLabel: { color: '#6b7793' }, splitLine: { lineStyle: { color: 'rgba(42,53,80,0.5)' } } },
    series: [
      { name: low ? low.name : '置信下界', type: 'line', data: low ? low.data : [], lineStyle: { width: 1, type: 'dashed', color: '#e6545a' }, itemStyle: { color: '#e6545a' }, areaStyle: { color: 'rgba(230,84,90,0.08)' } },
      { name: mid ? mid.name : '中位预测', type: 'line', data: mid ? mid.data : [], smooth: true, lineStyle: { width: 2, color: '#6366f1' }, itemStyle: { color: '#6366f1' }, symbolSize: 8 },
      { name: up ? up.name : '置信上界', type: 'line', data: up ? up.data : [], lineStyle: { width: 1, type: 'dashed', color: '#10b981' }, itemStyle: { color: '#10b981' }, areaStyle: { color: 'rgba(16,185,129,0.06)' } },
    ],
  }
}

function technicalOption(cd) {
  const dates = cd.x_axis || []
  const series = cd.series || []
  const price = series.find((s) => s.type === 'line' && (!s.name || !s.name.includes('MACD')))
  const macd = series.find((s) => s.type === 'bar' || (s.name && s.name.includes('MACD')))

  return {
    backgroundColor: 'transparent',
    legend: { data: series.map((s) => s.name), textStyle: { color: '#aab4c8' }, top: 0 },
    tooltip: { trigger: 'axis' },
    grid: [
      { left: 56, right: 20, top: 36, height: '64%' },
      { left: 56, right: 20, top: '78%', height: '16%' },
    ],
    xAxis: [
      { type: 'category', data: dates, axisLine: { lineStyle: { color: '#2a3550' } }, axisLabel: { color: '#6b7793' } },
      { type: 'category', gridIndex: 1, data: dates, axisLine: { lineStyle: { color: '#2a3550' } }, axisLabel: { show: false } },
    ],
    yAxis: [
      { scale: true, axisLine: { lineStyle: { color: '#2a3550' } }, axisLabel: { color: '#6b7793' }, splitLine: { lineStyle: { color: 'rgba(42,53,80,0.5)' } } },
      { gridIndex: 1, axisLine: { lineStyle: { color: '#2a3550' } }, axisLabel: { color: '#6b7793' }, splitLine: { show: false } },
    ],
    series: [
      { name: price ? price.name : '收盘价', type: 'line', data: price ? price.data : [], smooth: true, showSymbol: false, lineStyle: price && price.lineStyle ? price.lineStyle : { width: 1.5, color: '#22d3ee' }, itemStyle: { color: '#22d3ee' } },
      { name: macd ? macd.name : 'MACD柱', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: macd ? macd.data : [], itemStyle: { color: '#a855f7' } },
    ],
  }
}

export function buildChartOption(cd) {
  if (!cd || !cd.type) return null
  switch (cd.type) {
    case 'candlestick':
      return candlestickOption(cd)
    case 'prediction':
      return predictionOption(cd)
    case 'technical':
      return technicalOption(cd)
    default:
      return null
  }
}

export const CHART_META = {
  candlestick: { title: 'K线', icon: '📈' },
  prediction: { title: '价格预测', icon: '🔮' },
  technical: { title: '技术指标', icon: '🧮' },
}
