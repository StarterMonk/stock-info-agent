<script setup>
const props = defineProps({
  states: { type: Object, required: true },
  thinking: { type: Boolean, default: false },
})

const nodes = [
  { key: 'supervisor', label: '超级节点', sub: 'Supervisor · LLM 路由', color: 'var(--accent)', icon: '🧭' },
  { key: 'A', label: 'Agent A', sub: '数据获取 · AKShare 工具', color: 'var(--agent-a)', icon: '📡' },
  { key: 'C', label: 'Agent C', sub: '处理 · 预测模型', color: 'var(--agent-c)', icon: '🧠' },
  { key: 'B', label: 'Agent B', sub: '图表生成 · ECharts', color: 'var(--agent-b)', icon: '📊' },
  { key: 'assembler', label: 'Assembler', sub: '回复组装 · 分类', color: 'var(--accent-2)', icon: '🧩' },
]
</script>

<template>
  <div class="pipeline-card">
    <h2 class="card-title">多智能体编排</h2>
    <p class="card-sub">LangGraph StateGraph 流水线</p>

    <div class="nodes">
      <template v-for="(n, i) in nodes" :key="n.key">
        <div
          class="node"
          :class="states[n.key]"
          :style="{ '--nc': n.color }"
        >
          <div class="node-icon">{{ n.icon }}</div>
          <div class="node-text">
            <div class="node-label">{{ n.label }}</div>
            <div class="node-sub">{{ n.sub }}</div>
          </div>
          <div class="node-badge">
            <span v-if="states[n.key] === 'active'" class="dot spin"></span>
            <span v-else-if="states[n.key] === 'done'" class="tick">✓</span>
          </div>
        </div>
        <div v-if="i < nodes.length - 1" class="edge" :class="{ lit: states[n.key] === 'done' }">
          <span class="arrow">▶</span>
        </div>
      </template>
    </div>

    <div class="legend">
      <span><i class="sw idle"></i>待命</span>
      <span><i class="sw active"></i>执行中</span>
      <span><i class="sw done"></i>完成</span>
    </div>

    <div v-if="thinking" class="running-tip">● 多智能体协同分析中…</div>
  </div>
</template>

<style scoped>
.pipeline-card {
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 16px;
  box-shadow: var(--shadow);
  overflow-y: auto;
}
.card-title {
  font-size: 15px;
  color: var(--text-0);
}
.card-sub {
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 16px;
}
.nodes {
  display: flex;
  flex-direction: column;
  align-items: stretch;
}
.node {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--bg-2);
  transition: all 0.35s ease;
  opacity: 0.55;
}
.node.idle {
  border-color: var(--border);
}
.node.active {
  opacity: 1;
  border-color: var(--nc);
  box-shadow: 0 0 0 1px var(--nc), 0 0 18px -4px var(--nc);
  animation: pulse 1.6s infinite;
}
.node.done {
  opacity: 1;
  border-color: var(--ok);
}
.node-icon {
  font-size: 22px;
  width: 38px;
  height: 38px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  background: color-mix(in srgb, var(--nc) 18%, transparent);
}
.node-text {
  flex: 1;
}
.node-label {
  font-weight: 600;
  font-size: 14px;
}
.node-sub {
  font-size: 11px;
  color: var(--text-2);
}
.node-badge {
  width: 22px;
  display: grid;
  place-items: center;
}
.dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  border: 2px solid var(--nc);
  border-top-color: transparent;
  display: inline-block;
}
.spin {
  animation: spin 0.7s linear infinite;
}
.tick {
  color: var(--ok);
  font-weight: 700;
}
.edge {
  height: 18px;
  display: grid;
  place-items: center;
  color: var(--border);
  font-size: 10px;
  transition: color 0.3s;
}
.edge.lit {
  color: var(--ok);
}
.legend {
  display: flex;
  gap: 14px;
  margin-top: 16px;
  font-size: 11px;
  color: var(--text-2);
}
.legend .sw {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
  margin-right: 4px;
  vertical-align: -1px;
}
.sw.idle {
  background: var(--border);
}
.sw.active {
  background: var(--accent);
}
.sw.done {
  background: var(--ok);
}
.running-tip {
  margin-top: 14px;
  font-size: 12px;
  color: var(--accent-2);
  animation: fadeUp 0.4s ease;
}
</style>
