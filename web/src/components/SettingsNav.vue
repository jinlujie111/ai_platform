<template>
  <div class="vue-settings-nav">
    <div class="modal-nav-label">AI 与数据</div>
    <button
      v-for="item in groups.ai"
      :key="item.id"
      type="button"
      class="modal-nav-item"
      :class="{ active: active === item.id }"
      :data-panel="item.id"
      @click="select(item.id)"
    >
      <span class="vue-nav-icon" v-html="item.icon"></span>
      {{ item.label }}
      <span v-if="loading === item.id" class="vue-nav-loading">…</span>
    </button>

    <div class="modal-nav-label">平台能力</div>
    <button
      v-for="item in groups.platform"
      :key="item.id"
      type="button"
      class="modal-nav-item"
      :class="{ active: active === item.id }"
      :data-panel="item.id"
      @click="select(item.id)"
    >
      <span class="vue-nav-icon" v-html="item.icon"></span>
      {{ item.label }}
      <span v-if="loading === item.id" class="vue-nav-loading">…</span>
    </button>

    <div class="modal-nav-label">治理与输出</div>
    <button
      v-for="item in groups.gov"
      :key="item.id"
      type="button"
      class="modal-nav-item"
      :class="{ active: active === item.id }"
      :data-panel="item.id"
      @click="select(item.id)"
    >
      <span class="vue-nav-icon" v-html="item.icon"></span>
      {{ item.label }}
      <span v-if="loading === item.id" class="vue-nav-loading">…</span>
    </button>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue';
import { activatePanel } from '@/legacy/panels.js';

const active = ref('model');
const loading = ref('');

const icon = {
  model: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14M4.93 4.93a10 10 0 0 0 0 14.14"/></svg>',
  datasource: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
  kb: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>',
  mcp: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
  skill: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
  agent: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a4 4 0 0 1 4 4v1h1a3 3 0 0 1 0 6h-1v1a4 4 0 0 1-8 0v-1H7a3 3 0 0 1 0-6h1V6a4 4 0 0 1 4-4z"/><circle cx="9" cy="10" r="1"/><circle cx="15" cy="10" r="1"/></svg>',
  tool: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>',
  api: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
  dataprocess: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
  permission: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  dataoutput: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>',
};

const groups = {
  ai: [
    { id: 'model', label: '模型配置', icon: icon.model },
    { id: 'datasource', label: '数据源接入', icon: icon.datasource },
    { id: 'kb', label: '知识库', icon: icon.kb },
  ],
  platform: [
    { id: 'agent', label: 'Agent 管理', icon: icon.agent },
    { id: 'mcp', label: 'MCP 管理', icon: icon.mcp },
    { id: 'skill', label: 'Skill 管理', icon: icon.skill },
    { id: 'tool', label: 'Tool 设置', icon: icon.tool },
    { id: 'api', label: 'API 设置', icon: icon.api },
  ],
  gov: [
    { id: 'dataprocess', label: '数据处理', icon: icon.dataprocess },
    { id: 'permission', label: '权限与审计', icon: icon.permission },
    { id: 'dataoutput', label: '数据输出', icon: icon.dataoutput },
  ],
};

async function select(panelId) {
  active.value = panelId;
  loading.value = panelId;
  try {
    // Prefer legacy router (updates titles / panel visibility), then lazy-activate.
    if (typeof window.switchToPanel === 'function') {
      window.switchToPanel(panelId);
    }
    await activatePanel(panelId);
  } finally {
    loading.value = '';
  }
}

onMounted(() => {
  const current = document.querySelector('.modal-panel.active')?.id?.replace(/^panel-/, '');
  if (current) active.value = current;
});
</script>

<style scoped>
.vue-settings-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.vue-nav-icon {
  display: inline-flex;
  width: 15px;
  height: 15px;
}
.vue-nav-loading {
  margin-left: auto;
  opacity: 0.7;
  font-size: 12px;
}
</style>
