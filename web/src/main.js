import { createApp } from 'vue';
import SettingsNav from './components/SettingsNav.vue';
import { initApp } from './legacy/initApp.js';
import '../styles.css';

/**
 * Phase 3: Vue shell for settings navigation.
 * Phase 1–2: legacy initApp + dynamic panel chunks via panels.js.
 */
function mountVueShell() {
  const host = document.getElementById('vue-settings-nav');
  if (!host) return;
  createApp(SettingsNav).mount(host);
}

function boot() {
  initApp();
  mountVueShell();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
