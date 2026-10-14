import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 개발 중에는 /api를 FastAPI(127.0.0.1:8000)로 넘겨 CORS 설정 없이 같은 출처로 쓴다.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
