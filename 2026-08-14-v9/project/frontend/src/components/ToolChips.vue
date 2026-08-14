<script setup>
const props = defineProps({
  chips: { type: Array, default: () => [] },
})

const ICONS = {
  get_profile: '🏢',
  get_history: '📜',
  get_intraday: '⏱️',
  get_financials: '📒',
  get_dividend: '💸',
  get_capital_flow: '🌊',
  get_indicators: '📐',
  get_key_metrics: '📊',
  get_forecast: '📈',
  get_technical_indicators: '🧮',
  get_price_prediction: '🔮',
  search_stocks: '🔎',
}

function icon(name) {
  return ICONS[name] || '⚙️'
}
function short(name) {
  return name.replace('get_', '')
}
</script>

<template>
  <div v-if="chips.length" class="chips">
    <div v-for="(c, i) in chips" :key="i" class="chip" :title="c.name">
      <span class="chip-icon">{{ icon(c.name) }}</span>
      <span class="chip-name">{{ short(c.name) }}</span>
      <span class="chip-status">{{ c.status }}</span>
    </div>
  </div>
</template>

<style scoped>
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 8px 0;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 20px;
  background: var(--bg-3);
  border: 1px solid var(--border);
  font-size: 12px;
  animation: fadeUp 0.3s ease;
}
.chip-icon {
  font-size: 13px;
}
.chip-name {
  color: var(--text-1);
  font-family: var(--mono);
}
.chip-status {
  color: var(--ok);
  font-size: 11px;
}
</style>
