// 多智能体 SSE 引擎 + 渐进式揭示调度器。
// 真实模式：EventSource 连接 /api/chat/multi，事件入队后定时揭示。
// 演示模式：直接把 demoScript 事件序列喂给同一套揭示调度器，离线回放。
//
// 揭示过程中按事件顺序驱动 5 个智能体节点状态：
//   supervisor → A(数据获取) → C(处理预测) → B(图表生成) → assembler(组装)
// 后端整段执行后一次性吐事件，故"活起来"完全由前端定时器实现。

const IDLE = 'idle'
const ACTIVE = 'active'
const DONE = 'done'

function emptyStates() {
  return { supervisor: IDLE, A: IDLE, C: IDLE, B: IDLE, assembler: IDLE }
}

function categorize(text) {
  // 按 ### 头分块，再用关键词归桶
  const blocks = text.split(/^###\s+/m).filter((b) => b.trim())
  const cats = []
  const map = [
    { key: 'info', label: '概况', icon: '🏢', kw: ['公司', '简介', '主营', '行业', '板块', '概况'] },
    { key: 'quote', label: '行情', icon: '📊', kw: ['行情', '涨跌', '收盘', '开盘', '最高', '最低', 'K线', '走势'] },
    { key: 'analysis', label: '技术分析', icon: '🧮', kw: ['技术', '指标', 'MACD', 'RSI', '均线', '布林', '趋势', '动量'] },
    { key: 'forecast', label: '价格预测', icon: '🔮', kw: ['预测', '预估', '未来', '方向', '概率', '支撑', '压力'] },
    { key: 'finance', label: '财务', icon: '💰', kw: ['财务', '营收', '利润', '净利', 'ROE', '分红', '股息'] },
  ]
  for (const block of blocks) {
    const head = block.split('\n')[0]
    const body = block
    let target = map.find((m) => m.kw.some((k) => head.includes(k) || body.slice(0, 60).includes(k)))
    if (!target) target = map[1]
    cats.push({ ...target, text: `### ${block}` })
  }
  return cats
}

export function useMultiAgent() {
  let es = null
  let timers = []
  let aborted = false

  function clearTimers() {
    timers.forEach((t) => clearTimeout(t))
    timers = []
  }

  function stop() {
    aborted = true
    clearTimers()
    if (es) {
      es.close()
      es = null
    }
  }

  // 把归一化的事件序列按节奏揭示
  function play(events, cb) {
    aborted = false
    const states = emptyStates()
    const messages = cb.getMessages()
    const assistant = {
      id: 'a-' + Date.now(),
      role: 'assistant',
      text: '',
      chips: [],
      cats: [],
    }
    messages.push(assistant)
    cb.setMessages(messages)

    let i = 0
    let delay = 300

    const step = () => {
      if (aborted) return
      if (i >= events.length) {
        // 结束：全部完成
        states.supervisor = DONE
        states.A = DONE
        states.C = DONE
        states.B = DONE
        states.assembler = DONE
        cb.onAgentState({ ...states })
        // 分类
        assistant.cats = categorize(assistant.text)
        cb.setMessages([...messages])
        cb.onThinking(false)
        return
      }
      const ev = events[i]
      i += 1

      switch (ev.type) {
        case 'start':
          states.supervisor = ACTIVE
          cb.onAgentState({ ...states })
          delay = 500
          break
        case 'tool': {
          if (states.A === IDLE) states.A = ACTIVE
          states.supervisor = DONE
          const tc = typeof ev.data === 'string' ? safeParse(ev.data) : ev.data
          if (tc && tc.name) {
            assistant.chips.push({
              name: tc.name,
              status: tc.result_summary || '成功',
            })
            cb.setMessages([...messages])
          }
          delay = 420
          break
        }
        case 'chart': {
          states.A = DONE
          states.C = DONE
          states.B = ACTIVE
          const chart = typeof ev.data === 'string' ? safeParse(ev.data) : ev.data
          if (chart && chart.type) {
            cb.onCharts([...cb.getCharts(), chart])
            delay = 600
          }
          break
        }
        case 'chunk': {
          if (states.B === ACTIVE || states.B === DONE) states.B = DONE
          states.assembler = ACTIVE
          const line = typeof ev.data === 'string' ? ev.data : ''
          if (line) {
            assistant.text = assistant.text ? assistant.text + '\n' + line : line
            cb.setMessages([...messages])
            delay = 90
          }
          break
        }
        case 'done':
          delay = 200
          break
        case 'error': {
          assistant.text = '⚠️ ' + (typeof ev.data === 'string' ? ev.data : '处理失败')
          cb.setMessages([...messages])
          delay = 100
          break
        }
        default:
          delay = 100
      }
      timers.push(setTimeout(step, delay))
    }
    step()
  }

  function safeParse(s) {
    try {
      return JSON.parse(s)
    } catch {
      return null
    }
  }

  // 真实模式：EventSource 拉取后转成事件序列再 play
  function startReal(message, sessionId, cb) {
    cb.onThinking(true)
    const url = `/api/chat/multi?${new URLSearchParams({ session_id: sessionId, message })}`
    es = new EventSource(url)
    const buffer = []
    let started = false
    const kick = () => {
      if (started) return
      started = true
      if (es) {
        es.close()
        es = null
      }
      if (!buffer.find((b) => b.type === 'done')) buffer.push({ type: 'done', data: '完成' })
      play(buffer, cb)
    }
    const handlers = {
      start: (d) => buffer.push({ type: 'start', data: d }),
      tool: (d) => buffer.push({ type:'tool', data: d }),
      chart: (d) => buffer.push({ type: 'chart', data: d }),
      chunk: (d) => buffer.push({ type: 'chunk', data: d }),
      done: (d) => buffer.push({ type: 'done', data: d }),
      error: (d) => buffer.push({ type: 'error', data: d }),
    }
    for (const [ev, fn] of Object.entries(handlers)) {
      es.addEventListener(ev, (e) => fn(e.data))
    }
    es.addEventListener('done', () => setTimeout(kick, 250))
    es.onerror = () => kick()
  }

  function startDemo(demoEvents, cb) {
    cb.onThinking(true)
    play(demoEvents, cb)
  }

  return { startReal, startDemo, stop }
}
