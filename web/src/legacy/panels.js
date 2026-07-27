/** Panel lazy-load helpers (Vite code-splitting + API hooks) */

export const panelLoaders = {
  model: () => import('./parts/models_settings.js'),
  datasource: () => import('./parts/models_settings.js'),
  kb: () => import('./parts/knowledge.js'),
  agent: () => import('./parts/agent.js'),
  mcp: () => import('./parts/mcp.js'),
  skill: () => import('./parts/skill.js'),
  tool: () => import('./parts/setup.js'),
  dataprocess: () => import('./parts/pipelines.js'),
  permission: () => import('./parts/permission.js'),
  api: async () => ({ partId: 'api' }),
  dataoutput: async () => ({ partId: 'dataoutput' }),
};

export async function prefetchPanel(panelId) {
  const loader = panelLoaders[panelId];
  if (loader) await loader();
}

export async function activatePanel(panelId, api = window.__AI_PLATFORM__) {
  await prefetchPanel(panelId);
  if (!api) return;
  switch (panelId) {
    case 'model':
      api.renderModelList?.();
      break;
    case 'datasource':
      await api.loadDataSourcesFromApi?.();
      api.renderDataSourceList?.();
      break;
    case 'kb':
      api.initKnowledgeBasePanel?.();
      break;
    case 'agent':
      api.initAgentPanel?.();
      break;
    case 'mcp':
      api.initMcpPanel?.();
      break;
    case 'skill':
      api.initSkillPanel?.();
      break;
    case 'tool':
      api.initToolPanel?.();
      break;
    case 'dataprocess':
      await api.loadPipelines?.();
      break;
    case 'permission':
      api.initPermissionPanel?.();
      break;
    default:
      break;
  }
}
