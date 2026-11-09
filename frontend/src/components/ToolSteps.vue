<script setup>
import { Database, Globe } from 'lucide-vue-next'
import StatusIcon from './StatusIcon.vue'

defineProps({ steps: { type: Array, default: () => [] } })

const NAME_MAP = {
  knowledge_search: { label: '知识库检索', icon: Database },
  tavily_web_search: { label: '联网搜索', icon: Globe },
}
</script>

<template>
  <div v-if="steps.length" class="steps">
    <div v-for="(s, i) in steps" :key="i" class="step" :class="s.status">
      <component
        :is="(NAME_MAP[s.name]?.icon || Database)"
        :size="13"
        class="step-ico"
      />
      <span class="step-label">{{ NAME_MAP[s.name]?.label || s.name }}</span>
      <StatusIcon :status="s.status" :size="12" />
      <span v-if="s.status === 'done'" class="step-meta">
        <template v-if="s.product && s.product.length">
          <span class="step-scope">{{ s.product.join('、') }}</span> ·
        </template>
        {{ s.hits ?? 0 }} 条结果<template v-if="s.top_score != null">
          · 最高相关度 {{ Number(s.top_score).toFixed(2) }}
        </template>
      </span>
      <span v-else-if="s.status === 'running'" class="step-meta running-text">
        {{ s.name === 'tavily_web_search' ? '正在联网搜索…' : '正在检索…' }}
      </span>
      <span v-else class="step-meta err-text">{{ s.error || '失败' }}</span>
    </div>
  </div>
</template>

<style scoped>
.steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.step {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  border: 1px solid var(--line);
  background: rgba(34, 211, 238, 0.06);
  color: var(--muted);
}
.step.running {
  border-color: var(--line-strong);
  color: var(--cyan);
  box-shadow: 0 0 10px rgba(34, 211, 238, 0.15);
}
.step.done {
  color: #8fdcec;
}
.step.error {
  color: var(--danger);
  border-color: rgba(248, 113, 113, 0.4);
  background: rgba(248, 113, 113, 0.07);
}
.step-ico {
  flex-shrink: 0;
}
.step-meta {
  color: var(--muted);
}
.step-scope {
  color: var(--cyan);
  font-weight: 600;
}
.running-text {
  color: var(--cyan);
}
.err-text {
  color: var(--danger);
}
</style>
