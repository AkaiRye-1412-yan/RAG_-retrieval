<script setup>
import { Loader2, CheckCircle2, AlertTriangle } from 'lucide-vue-next'

defineProps({
  status: { type: String, default: 'running' }, // running | done | error
  size: { type: Number, default: 12 },
})
</script>

<template>
  <Loader2 v-if="status === 'running'" :size="size" class="spin" />
  <CheckCircle2 v-else-if="status === 'done'" :size="size" class="ok" />
  <AlertTriangle v-else :size="size" class="err" />
</template>

<style scoped>
.ok {
  color: var(--ok);
}
.err {
  color: var(--danger);
}
</style>
