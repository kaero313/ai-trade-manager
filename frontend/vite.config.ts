import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173 },
  build: {
    rollupOptions: {
      output: {
        // 무거운 시각화 라이브러리를 leaf 청크로 격리해 병렬 로딩·독립 캐싱한다.
        // recharts(+d3)는 포트폴리오·연구소, lightweight-charts는 대시보드·연구소에서만 쓰인다.
        manualChunks(id) {
          if (!id.includes('node_modules')) {
            return undefined
          }
          if (id.includes('lightweight-charts')) {
            return 'charts-lightweight'
          }
          if (id.includes('recharts') || id.includes('/d3-') || id.includes('victory-vendor')) {
            return 'charts-recharts'
          }
          return undefined
        },
      },
    },
  },
})
