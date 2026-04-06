import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '../', '')
  return {
    plugins: [react()],
    base: '/meniubot_admin/',
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/meniubot/api': {
          target: env.API_URL || 'http://localhost:5000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/meniubot\/api/, '/api'),
        },
      },
    },
  }
})
