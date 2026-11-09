<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useAppStore } from './stores/app'
import SideBar from './components/SideBar.vue'
import KeyBanner from './components/KeyBanner.vue'
import ChatView from './views/ChatView.vue'
import LibraryView from './views/LibraryView.vue'
import SettingsView from './views/SettingsView.vue'

const app = useAppStore()
let timer = null

onMounted(() => {
  app.refreshStatus()
  timer = setInterval(app.refreshStatus, 5000)
})
onUnmounted(() => timer && clearInterval(timer))
</script>

<template>
  <div class="shell">
    <SideBar />
    <div class="main">
      <KeyBanner />
      <div class="view-wrap">
        <KeepAlive>
          <ChatView v-if="app.view === 'chat'" />
          <LibraryView v-else-if="app.view === 'library'" />
          <SettingsView v-else />
        </KeepAlive>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100%;
}
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.view-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
}
.view-wrap > * {
  flex: 1;
  min-width: 0;
}
</style>
