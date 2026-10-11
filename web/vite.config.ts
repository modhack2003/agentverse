import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { Agent } from 'node:http'

// Keep upgraded WebSocket connections separate from proxied HTTP requests.
const proxyAgent = new Agent({ keepAlive: false })

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', ws: true, agent: proxyAgent, proxyTimeout: 15000, timeout: 15000 },
      '/mcp': { target: 'http://127.0.0.1:8000', agent: proxyAgent, proxyTimeout: 15000, timeout: 15000 },
    },
  },
})
