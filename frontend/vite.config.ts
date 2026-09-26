import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Same-origin /api proxy in dev so cookie auth + CSRF never need CORS --
// mirrors the nginx reverse proxy used in the built image (see Dockerfile).
const backendTarget = process.env.VITE_BACKEND_ORIGIN ?? 'http://localhost:8001'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
})
