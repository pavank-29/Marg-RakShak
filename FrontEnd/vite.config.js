import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({mode}) => ({
  plugins: [react()],
  server: {
    port: 3000,
    open: true,
    proxy: mode === 'development' ? {
      '/api': {
        // Dev proxy: points to local FastAPI backend
        // On Render, VITE_API_URL is set and api.js uses it directly — no proxy needed in production build
        target: process.env.VITE_API_URL || 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      }
    } : undefined
  },
  build: {
    // Raise chunk size warning limit to avoid noise
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          // Vendor: React core
          'react-vendor': ['react', 'react-dom'],
          // Routing
          'router': ['react-router-dom'],
          // Map libraries (largest dependency)
          'leaflet-vendor': ['leaflet', 'react-leaflet'],
          // Icons
          'icons': ['lucide-react'],
        }
      }
    }
  }
}))
