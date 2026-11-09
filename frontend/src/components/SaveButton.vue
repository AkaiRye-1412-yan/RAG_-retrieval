<script setup>
import { Save } from 'lucide-vue-next'

defineProps({ saving: { type: Boolean, default: false } })
const emit = defineEmits(['click'])
</script>

<template>
  <button class="btn btn-primary" :disabled="saving" @click="emit('click')">
    <Save :size="14" /> {{ saving ? '保存中…' : '保存配置' }}
  </button>
</template>
