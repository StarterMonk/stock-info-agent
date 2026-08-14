<script setup>
import { ref, watch } from 'vue'
import ToolChips from './ToolChips.vue'

const props = defineProps({
  msg: { type: Object, required: true },
})

const activeCat = ref(0)
watch(
  () => props.msg.cats,
  (cats) => {
    if (cats && cats.length) activeCat.value = 0
  },
  { deep: true }
)

function fmt(text) {
  if (!text) return ''
  return text
    .replace(/^###\s+/m, '')
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/^- (.+)$/gm, '<span class="li">• $1</span>')
    .replace(/^&gt;\s?(.+)$/gm, '<span class="quote">$1</span>')
}
</script>

<template>
  <div class="bubble" :class="msg.role">
    <div class="role">{{ msg.role === 'user' ? '你' : 'Stock Agent' }}</div>

    <template v-if="msg.role === 'assistant'">
      <ToolChips :chips="msg.chips" />

      <div v-if="!msg.cats || !msg.cats.length" class="raw" v-html="fmt(msg.text)"></div>

      <div v-else class="cats">
        <div class="tabs">
          <button
            v-for="(c, i) in msg.cats"
            :key="i"
            :class="{ active: i === activeCat }"
            @click="activeCat = i"
          >
            {{ c.icon }} {{ c.label }}
          </button>
        </div>
        <div class="cat-body" v-html="fmt(msg.cats[activeCat].text)"></div>
      </div>
    </template>

    <div v-else class="raw user" v-html="fmt(msg.text)"></div>
  </div>
</template>

<style scoped>
.bubble {
  margin-bottom: 14px;
  animation: fadeUp 0.25s ease;
}
.role {
  font-size: 11px;
  color: var(--text-2);
  margin-bottom: 4px;
}
.bubble.user .role {
  text-align: right;
}
.raw {
  padding: 12px 14px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.raw.user {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.li {
  display: block;
  color: var(--text-1);
}
.quote {
  display: block;
  color: var(--text-2);
  font-size: 12px;
  border-left: 2px solid var(--border);
  padding-left: 8px;
  margin-top: 4px;
}
.tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0;
}
.tabs button {
  padding: 5px 10px;
  font-size: 12px;
  border-radius: 8px;
}
.tabs button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.cat-body {
  padding: 12px 14px;
  background: var(--bg-2);
  border: 1px solid var(--border);
  border-radius: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
