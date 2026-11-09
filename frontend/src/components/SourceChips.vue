<script setup>
import { ref } from 'vue'
import { FileText, Globe, ChevronDown } from 'lucide-vue-next'

defineProps({ items: { type: Array, default: () => [] } })
const open = ref(null)
function toggle(i) {
  open.value = open.value === i ? null : i
}
</script>

<template>
  <div v-if="items.length" class="sources">
    <div class="sources-title">参考来源</div>
    <div class="chips">
      <button
        v-for="(it, i) in items"
        :key="i"
        class="chip"
        :class="{ web: it.kind === 'web' }"
        @click="toggle(i)"
      >
        <component :is="it.kind === 'web' ? Globe : FileText" :size="12" />
        <span class="ref">[{{ it.ref }}]</span>
        <span class="name">{{ it.kind === 'web' ? it.title : it.doc_name }}</span>
        <ChevronDown :size="11" class="caret" />
      </button>
    </div>
    <transition name="expand">
      <div v-if="open !== null" class="pop">
        <template v-if="items[open].kind === 'web'">
          <a :href="items[open].url" target="_blank" rel="noopener" class="pop-title">
            <Globe :size="12" /> {{ items[open].title || items[open].url }}
          </a>
        </template>
        <template v-else>
          <div class="pop-title">
            <FileText :size="12" />
            《{{ items[open].doc_name }}》{{ items[open].label ? ' · ' + items[open].label : '' }}
            <span v-if="items[open].score != null" class="score">
              相关度 {{ Number(items[open].score).toFixed(2) }}
            </span>
          </div>
        </template>
        <div class="snippet">{{ items[open].snippet }}</div>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.sources {
  margin-top: 10px;
}
.sources-title {
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 280px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(34, 211, 238, 0.06);
  color: var(--muted);
  font-size: 12px;
  transition: all 0.15s;
}
.chip:hover {
  border-color: var(--line-strong);
  color: var(--cyan);
}
.chip.web {
  background: rgba(129, 140, 248, 0.08);
  border-color: rgba(129, 140, 248, 0.3);
}
.ref {
  color: var(--cyan);
  font-weight: 600;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.caret {
  opacity: 0.6;
}
.pop {
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: rgba(8, 17, 32, 0.85);
}
.pop-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--cyan);
  font-weight: 600;
  margin-bottom: 6px;
}
a.pop-title {
  text-decoration: none;
}
a.pop-title:hover {
  text-decoration: underline;
}
.score {
  margin-left: auto;
  color: var(--muted);
  font-weight: 400;
}
.snippet {
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.7;
  white-space: pre-wrap;
  max-height: 170px;
  overflow-y: auto;
}
.expand-enter-active,
.expand-leave-active {
  transition: all 0.18s ease;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
