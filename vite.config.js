import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // The Python API (server.py) holds the TypeSafe key and runs the search.
    proxy: { '/api': 'http://127.0.0.1:8787' },
  },
})
