<script setup>
import { ref } from 'vue'
import AgentPipeline from './components/AgentPipeline.vue'
import ChatPanel from './components/ChatPanel.vue'
import ChartDock from './components/ChartDock.vue'
import { demoScript } from './data/demoScript.js'

const pipeline = ref(null)
const chartDock = ref(null)
const messages = ref([])
const agentStates = ref({ supervisor: 'idle', A: 'idle', C: 'idle', B: 'idle', assembler: 'idle' })
const charts = ref([])
const thinking = ref(false)
const demoMode = ref(false)

function onAgentState(states) {
  agentStates.value = states
}

function onMessages(msgs) {
  messages.value = msgs
}

function onCharts(list) {
  charts.value = list
}

function onThinking(v) {
  thinking.value = v
}

function resetAll() {
  messages.value = []
  charts.value = []
  agentStates.value = { supervisor: 'idle', A: 'idle', C: 'idle', B: 'idle', assembler: 'idle' }
  thinking.value = false
}
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <div class="brand">
        <span class="logo">◆</span>
        <div>
          <h1>Stock Agent <span class="v">v9</span></h1>
          <p>多智能体 A股分析助手 · LangGraph Orchestration</p>
        </div>
      </div>
      <div class="mode-switch">
        <span class="mode-label">模式</span>
        <button :class="{ active: !demoMode }" @click="demoMode = false">真实后端</button>
        <button :class="{ active: demoMode }" @click="demoMode = true">演示模式</button>
        <span v-if="demoMode" class="demo-hint">⏺ 离线预录回放 · 稳定可复现</span>
      </div>
    </header>

    <main class="grid">
      <aside class="col-pipeline">
        <AgentPipeline :states="agentStates" :thinking="thinking" />
      </aside>

      <section class="col-chat">
        <ChatPanel
          :demo-mode="demoMode"
          :messages="messages"
          :charts="charts"
          :thinking="thinking"
          @agent-state="onAgentState"
          @messages="onMessages"
          @charts="onCharts"
          @thinking="onThinking"
          @reset="resetAll"
        />
      </section>

      <aside class="col-chart">
        <ChartDock ref="chartDock" :charts="charts" />
      </aside>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 22px;
  border-bottom: 1px solid var(--border);
  background: rgba(17, 23, 38, 0.7);
  backdrop-filter: blur(8px);
}
.brand {
  display: flex;
  align-items: center;
  gap: 14px;
}
.logo {
  font-size: 28px;
  color: var(--accent);
  filter: drop-shadow(0 0 8px rgba(99, 102, 241, 0.6));
}
.brand h1 {
  font-size: 19px;
  letter-spacing: 0.5px;
}
.brand .v {
  color: var(--accent-2);
  font-size: 13px;
  border: 1px solid var(--accent-2);
  border-radius: 6px;
  padding: 0 6px;
  margin-left: 4px;
}
.brand p {
  font-size: 12px;
  color: var(--text-2);
}
.mode-switch {
  display: flex;
  align-items: center;
  gap: 8px;
}
.mode-label {
  font-size: 12px;
  color: var(--text-2);
}
.mode-switch button.active {
  border-color: var(--accent);
  background: var(--accent);
  color: #fff;
}
.demo-hint {
  font-size: 12px;
  color: var(--warn);
  margin-left: 6px;
}
.grid {
  flex: 1;
  display: grid;
  grid-template-columns: 280px 1fr 420px;
  gap: 14px;
  padding: 14px;
  min-height: 0;
}
.col-pipeline,
.col-chat,
.col-chart {
  min-height: 0;
  display: flex;
  flex-direction: column;
}
@media (max-width: 1100px) {
  .grid {
    grid-template-columns: 1fr;
    grid-auto-rows: minmax(200px, auto);
    overflow: auto;
  }
}
</style>
