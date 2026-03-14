import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  // Build output goes directly into the Python package's static directory
  // so it is picked up by FastAPI's StaticFiles mount and shipped in the wheel.
  build: {
    outDir: '../ui_server/static',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          // Split heavy deps into separate chunks for faster initial load
          vendor: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
          charts: ['recharts'],
        },
      },
    },
  },
  // Proxy API calls to the FastAPI backend during development
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:7432',
        changeOrigin: true,
      },
    },
  },
})
