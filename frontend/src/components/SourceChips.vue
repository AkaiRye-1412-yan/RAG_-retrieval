<script setup>
import { computed } from 'vue'
import { FileText, Globe } from 'lucide-vue-next'

const props = defineProps({
  items: { type: Array, default: () => [] },
  content: { type: String, default: '' },
})

// 只保留回答正文里真正引用过的编号（[1]、[2]…）；模型未标注时回退展示全部来源。
const usedItems = computed(() => {
  const cited = new Set(
    [...props.content.matchAll(/\[(\d{1,3})\]/g)].map((m) => Number(m[1])),
  )
  if (!cited.size) return props.items
  const filtered = props.items.filter((it) => cited.has(Number(it.ref)))
  return filtered.length ? filtered : props.items
})

// 同一份文档可能命中多个片段：这里按文档去重，只展示文档名，
// 不显示引用编号、页码/相关度/原文片段。
const docs = computed(() => {
  const out = []
  const map = new Map()
  for (const it of usedItems.value) {
    const isWeb = it.kind === 'web'
    const key = isWeb ? 'web:' + (it.url || it.title) : 'kb:' + (it.doc_id || it.doc_name)
    let entry = map.get(key)
    if (!entry) {
      entry = {
        key,
        web: isWeb,
        name: isWeb ? it.title || it.url : it.doc_name,
        url: it.url || '',
      }
      map.set(key, entry)
      out.push(entry)
    }
  }
  return out
})
</script>

<template>
  <div v-if="docs.length" class="sources">
    <div class="sources-title">参考来源</div>
    <div class="chips">
      <template v-for="d in docs" :key="d.key">
        <a
          v-if="d.web"
          class="chip web"
          :href="d.url"
          target="_blank"
          rel="noopener"
        >
          <Globe :size="12" />
          <span class="name">{{ d.name }}</span>
        </a>
        <span v-else class="chip">
          <FileText :size="12" />
          <span class="name">{{ d.name }}</span>
        </span>
      </template>
    </div>
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
  max-width: 360px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: rgba(34, 211, 238, 0.06);
  color: var(--muted);
  font-size: 12px;
  text-decoration: none;
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
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
