<script setup>
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as echarts from 'echarts'
import { buildChartOption, CHART_META } from '../composables/useChartOption.js'

const props = defineProps({
  charts: { type: Array, default: () => [] },
})

const active = ref(0)
const container = ref(null)
let chart = null
let resizeHandler = null

function render() {
  if (!container.value) return
  const cd = props.charts[active.value]
  if (!cd) return
  if (!chart) {
    chart = echarts.init(container.value, 'dark')
    chart.getZr().setCursorStyle('default')
  }
  const option = buildChartOption(cd)
  if (option) chart.setOption(option, true)
}

function metaOf(cd) {
  const m = CHART_META[cd.type] || { title: cd.type, icon: '📈' }
  return m
}

watch(
  () => props.charts,
  () => {
    if (active.value >= props.charts.length) active.value = 0
    nextTick(render)
  }
)
watch(active, () => nextTick(render))

onMounted(() => {
  nextTick(render)
  resizeHandler = () => chart && chart.resize()
  window.addEventListener('resize', resizeHandler)
})
onBeforeUnmount(() => {
  if (resizeHandler) window.removeEventListener('resize', resizeHandler)
  if (chart) {
    chart.dispose()
    chart = null
  }
})
</script>

<template>
  <div class="dock-card">
    <div class="dock-head">
      <span>图表坞</span>
      <span v-if="charts.length" class="count">{{ charts.length }} 张</span>
    </div>

    <div v-if="!charts.length" class="dock-empty">
      <div class="empty-icon">📈</div>
      <p>Agent B 生成的图表将在此展示</p>
    </div>

    <template v-else>
      <div class="tabs">
        <button
          v-for="(c, i) in charts"
          :key="i"
          :class="{ active: i === active }"
          @click="active = i"
        >
          {{ metaOf(c).icon }} {{ metaOf(c).title }}
        </button>
      </div>

      <div ref="container" class="chart-box"></div>

      <div v-if="charts[active] && charts[active].indicators" class="indicators">
        <div v-for="(v, k) in charts[active].indicators" :key="k" class="ind">
          <span class="ind-k">{{ k }}</span>
          <span class="ind-v">{{ v }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dock-card {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-1);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.dock-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 14px;
  font-weight: 600;
}
.count {
  font-size: 12px;
  color: var(--text-2);
}
.dock-empty {
  flex: 1;
  display: grid;
  place-items: center;
  color: var(--text-2);
  text-align: center;
}
.empty-icon {
  font-size: 38px;
  margin-bottom: 8px;
}
.tabs {
  display: flex;
  gap: 6px;
  padding: 10px 12px;
  flex-wrap: wrap;
}
.tabs button {
  font-size: 12px;
  padding: 5px 10px;
  border-radius: 8px;
}
.tabs button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.chart-box {
  flex: 1;
  min-height: 280px;
  width: 100%;
}
.indicators {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 10px 14px 16px;
  border-top: 1px solid var(--border);
}
.ind {
  display: flex;
  flex-direction: column;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 12px;
  min-width: 90px;
}
.ind-k {
  font-size: 11px;
  color: var(--text-2);
}
.ind-v {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-0);
}
</style>
