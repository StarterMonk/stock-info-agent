<script setup>
import { ref } from 'vue'
import { useMultiAgent } from '../composables/useMultiAgent.js'
import { demoScript } from '../data/demoScript.js'
import MessageBubble from './MessageBubble.vue'

const props = defineProps({
  demoMode: { type: Boolean, default: false },
  messages: { type: Array, required: true },
  charts: { type: Array, default: () => [] },
  thinking: { type: Boolean, default: false },
})
const emit = defineEmits(['agent-state', 'messages', 'charts', 'thinking', 'reset'])

const input = ref('')
const engine = useMultiAgent()
let sessionId = 'sess-' + Date.now()

function newSession() {
  sessionId = 'sess-' + Date.now()
  emit('reset')
  engine.stop()
}

function cb() {
  return {
    getMessages: () => props.messages,
    setMessages: (m) => emit('messages', m),
    getCharts: () => props.charts,
    onCharts: (c) => emit('charts', c),
    onAgentState: (s) => emit('agent-state', s),
    onThinking: (v) => emit('thinking', v),
  }
}

function send() {
  const text = input.value.trim()
  if (!text || props.thinking) return
  input.value = ''
  engine.stop()

  const userMsg = { id: 'u-' + Date.now(), role: 'user', text }
  emit('messages', [...props.messages, userMsg])

  if (props.demoMode) {
    engine.startDemo(demoScript, cb())
  } else {
    engine.startReal(text, sessionId, cb())
  }
}

const samples = ['600519 贵州茅台预测', '分析宁德时代 300750', '比亚迪 002594 走势']
function useSample(s) {
  if (props.thinking) return
  input.value = s
  send()
}
</script>

<template>
  <div class="chat-card">
    <div class="chat-head">
      <span>对话</span>
      <button class="ghost" @click="newSession">＋ 新会话</button>
    </div>

    <div class="messages" id="msg-scroll">
      <div v-if="!messages.length" class="empty">
        <div class="empty-icon">💬</div>
        <p>输入股票代码或名称，体验多智能体协同分析</p>
        <div class="samples">
          <button v-for="s in samples" :key="s" @click="useSample(s)">{{ s }}</button>
        </div>
      </div>

      <MessageBubble v-for="(m, i) in messages" :key="m.id || i" :msg="m" />
    </div>

    <div class="composer">
      <textarea
        v-model="input"
        rows="2"
        placeholder="例如：600519 预测未来走势"
        @keydown.enter.exact.prevent="send"
      ></textarea>
      <button class="send" :disabled="thinking || !input.trim()" @click="send">
        {{ thinking ? '分析中…' : '发送' }}
      </button>
    </div>
    <div class="hint">Enter 发送 · 多智能体 SSE 流式响应</div>
  </div>
</template>

<style scoped>
.chat-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  font-weight: 600;
}
.ghost {
  padding: 5px 10px;
  font-size: 12px;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.empty {
  text-align: center;
  color: var(--text-2);
  margin-top: 60px;
}
.empty-icon {
  font-size: 40px;
  margin-bottom: 10px;
}
.samples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 16px;
}
.samples button {
  font-size: 12px;
  padding: 6px 12px;
}
.composer {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  align-items: flex-end;
}
.composer textarea {
  flex: 1;
  resize: none;
}
.send {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  font-weight: 600;
}
.hint {
  font-size: 11px;
  color: var(--text-2);
  text-align: center;
  padding-bottom: 8px;
}
</style>
