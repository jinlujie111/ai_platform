import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import path from 'node:path';

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  root: '.',
  // Production assets are served by FastAPI under /static/dist/*
  base: command === 'build' ? '/static/dist/' : '/',
  publicDir: 'public',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/vue')) return 'vue';
          if (id.includes('/src/legacy/parts/knowledge')) return 'panel-kb';
          if (id.includes('/src/legacy/parts/pipelines')) return 'panel-pipelines';
          if (id.includes('/src/legacy/parts/')) return 'panel-parts';
          if (id.includes('/src/legacy/initApp')) return 'legacy-app';
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
}));
