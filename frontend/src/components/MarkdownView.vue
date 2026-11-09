<script setup>
import { onMounted, ref, watch } from 'vue'
import { bindCopyButtons, renderMarkdown } from '../utils/markdown'

const props = defineProps({ content: { type: String, default: '' } })
const el = ref(null)

function render() {
  if (el.value) el.value.innerHTML = renderMarkdown(props.content)
}

onMounted(() => {
  render()
  if (el.value) bindCopyButtons(el.value)
})
watch(() => props.content, render)
</script>

<template>
  <div ref="el" class="md-body"></div>
</template>
