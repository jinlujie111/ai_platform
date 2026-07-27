# Frontend (Vite + Vue)

## Develop
```powershell
cd web
npm install
npm run dev
```
Open http://localhost:5173 (API proxied to :8000).

## Production build (required for uvicorn :8000)
```powershell
cd web
npm install
npm run build
```
Then start FastAPI; it serves `web/dist` when present.

## Structure
- `src/main.js` — entry (Vue shell + legacy boot)
- `src/components/SettingsNav.vue` — settings nav (Vue)
- `src/lib/` — shared utils / dialog helpers
- `src/legacy/initApp.js` — original app logic (ES module)
- `src/legacy/parts/` — panel stubs for code-splitting
- `src/legacy/panels.js` — dynamic `import()` per panel
