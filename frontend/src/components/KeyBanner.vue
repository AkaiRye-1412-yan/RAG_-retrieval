<script setup>
import { TriangleAlert, ArrowRight } from 'lucide-vue-next'
import { useAppStore } from '../stores/app'
const app = useAppStore()
</script>

<template>
  <div v-if="!app.arkConfigured" class="banner">
    <div class="left">
      <TriangleAlert :size="17" class="ico" />
      <span>
        尚未配置 AI 密钥：向量库、文档解析与本地数据均可用；<b>AI 问答 / 文档嵌入 / 联网搜索需要密钥</b>，请先到系统配置填写。
      </span>
    </div>
    <button class="go" @click="app.setView('settings')">
      前往设置 <ArrowRight :size="14" />
    </button>
  </div>
</template>

<style scoped>
.banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 12px 16px 0;
  padding: 10px 16px;
  border-radius: 10px;
  background: linear-gradient(90deg, rgba(245, 158, 11, 0.14), rgba(245, 158, 11, 0.05));
  border: 1px solid rgba(245, 158, 11, 0.35);
  font-size: 13px;
  color: #fcd9a0;
}
.left {
  display: flex;
  align-items: center;
  gap: 9px;
}
.left b {
  color: #fbbf24;
}
.ico {
  color: var(--warn);
  flex-shrink: 0;
}
.go {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--warn);
  font-size: 13px;
  white-space: nowrap;
}
.go:hover {
  color: #fcd34d;
  text-decoration: underline;
}
</style>
