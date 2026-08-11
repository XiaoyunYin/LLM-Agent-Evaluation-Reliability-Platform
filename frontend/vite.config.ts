import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The FastAPI backend runs on :8000. We proxy `/api/*` to it from the Vite dev
// server instead of calling http://127.0.0.1:8000 directly from the browser,
// which would be a cross-origin request the backend does not currently allow
// (no CORSMiddleware in backend/main.py).
//
// 127.0.0.1 rather than `localhost`: on this machine `localhost` resolves to
// ::1 first, which cost a debugging session against Elasticsearch (build log,
// Session 15). Same trap applies here.
const BACKEND_ORIGIN = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
        // The backend has no /api prefix: /api/eval-runs -> /eval-runs
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
