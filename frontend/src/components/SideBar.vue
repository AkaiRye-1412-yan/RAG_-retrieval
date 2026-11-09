<script setup>
import { computed } from 'vue'
import { MessageSquareText, Database, Settings2 } from 'lucide-vue-next'
import { useAppStore } from '../stores/app'

const app = useAppStore()
const nav = computed(() => [
  { key: 'chat', label: '检索聊天', icon: MessageSquareText },
  { key: 'library', label: '向量库', icon: Database },
  { key: 'settings', label: '系统配置', icon: Settings2 },
])
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="logo">A</div>
      <div class="brand-text">
        <div class="brand-name">AkaiRye</div>
        <div class="brand-sub">知识RAG平台</div>
      </div>
    </div>

    <nav class="nav">
      <button
        v-for="item in nav"
        :key="item.key"
        class="nav-item"
        :class="{ active: app.view === item.key }"
        @click="app.setView(item.key)"
      >
        <component :is="item.icon" :size="17" :stroke-width="2" />
        <span>{{ item.label }}</span>
      </button>
    </nav>

    <div class="status">
      <span class="dot" :class="app.arkConfigured ? 'dot-ok' : 'dot-live'"></span>
      <span>{{ app.arkConfigured ? 'AI 已配置' : 'AI 未配置' }}</span>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 208px;
  flex-shrink: 0;
  background: linear-gradient(180deg, #0c1c33, #081120);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  padding: 18px 12px 14px;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 8px 18px;
}
.logo {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 20px;
  color: #04222b;
  background: linear-gradient(135deg, #67e8f9, #06b6d4);
  box-shadow: 0 0 16px rgba(34, 211, 238, 0.45);
}
.brand-name {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-strong);
  letter-spacing: 0.3px;
}
.brand-sub {
  font-size: 11.5px;
  color: var(--muted);
  margin-top: 1px;
}
.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 9px;
  color: var(--muted);
  font-size: 13.5px;
  transition: all 0.15s;
  text-align: left;
}
.nav-item:hover {
  color: var(--text);
  background: rgba(34, 211, 238, 0.07);
}
.nav-item.active {
  color: var(--cyan);
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.16), rgba(34, 211, 238, 0.03));
  box-shadow: inset 2px 0 0 var(--cyan);
  text-shadow: 0 0 12px rgba(34, 211, 238, 0.5);
}
.status {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  font-size: 12px;
  color: var(--muted);
  border-top: 1px solid var(--line);
}
</style>
