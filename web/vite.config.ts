import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { spawn, type ChildProcess } from 'child_process'
import net from 'net'

// https://vitejs.dev/config/
function devStackLauncher(): Plugin {
  const repoRoot = path.resolve(__dirname, '..')
  const backendHost = '127.0.0.1'
  const backendPort = 8012
  const frontendPort = 5173

  let backendProc: ChildProcess | null = null

  const isPortOpen = async (host: string, port: number, timeoutMs: number): Promise<boolean> => {
    return await new Promise((resolve) => {
      const socket = new net.Socket()
      const done = (ok: boolean) => {
        try { socket.destroy() } catch {}
        resolve(ok)
      }
      socket.setTimeout(timeoutMs)
      socket.once('error', () => done(false))
      socket.once('timeout', () => done(false))
      socket.connect(port, host, () => done(true))
    })
  }

  const waitForPort = async (host: string, port: number, timeoutMs: number): Promise<boolean> => {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
      // eslint-disable-next-line no-await-in-loop
      if (await isPortOpen(host, port, 250)) return true
      // eslint-disable-next-line no-await-in-loop
      await new Promise((r) => setTimeout(r, 250))
    }
    return false
  }

  const startBackendIfNeeded = async (): Promise<{ started: boolean; running: boolean; error?: string }> => {
    if (await isPortOpen(backendHost, backendPort, 200)) return { started: false, running: true }

    // If we previously spawned one and it died, clear it out.
    if (backendProc && backendProc.exitCode != null) backendProc = null

    // Spawn a detached backend (dev-only). Use `--reload` so the backend can self-restart.
    // Note: we intentionally discard stdio to keep Vite logs clean.
    try {
      backendProc = spawn(
        'uv',
        [
          'run',
          'uvicorn',
          'server.main:app',
          '--host',
          backendHost,
          '--port',
          String(backendPort),
          '--reload',
          '--log-level',
          'warning',
        ],
        {
          cwd: repoRoot,
          env: process.env,
          detached: true,
          stdio: 'ignore',
        }
      )
      backendProc.unref()
    } catch (e: any) {
      return { started: false, running: false, error: e?.message || String(e) }
    }

    const ok = await waitForPort(backendHost, backendPort, 15000)
    return ok ? { started: true, running: true } : { started: true, running: false, error: 'Backend did not become reachable' }
  }

  // Dev-only endpoints served by Vite, so the UI can recover when the backend is down.
  const json = (res: any, code: number, body: any) => {
    res.statusCode = code
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify(body))
  }

  return {
    name: 'tribrid-dev-stack-launcher',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        const url = String(req.url || '')
        if (url.startsWith('/__dev__/dev/status') && req.method === 'GET') {
          const backend_running = await isPortOpen(backendHost, backendPort, 200)
          return json(res, 200, {
            frontend_running: true,
            backend_running,
            frontend_port: frontendPort,
            backend_port: backendPort,
            frontend_url: `http://127.0.0.1:${frontendPort}/web`,
            backend_url: `http://${backendHost}:${backendPort}/api`,
            details: backend_running ? [] : ['Backend not reachable; use the Dev Stack buttons to start it.'],
          })
        }
        if (url.startsWith('/__dev__/dev/backend/start') && req.method === 'POST') {
          const result = await startBackendIfNeeded()
          if (!result.running) {
            return json(res, 500, {
              ok: false,
              error: result.error || 'Failed to start backend',
            })
          }
          return json(res, 200, {
            ok: true,
            started: result.started,
            backend_port: backendPort,
          })
        }
        return next()
      })
    },
  }
}

export default defineConfig({
  // Ensure built assets resolve under FastAPI mount at /web
  base: '/web/',
  plugins: [devStackLauncher(), react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@/components': path.resolve(__dirname, './src/components'),
      '@/stores': path.resolve(__dirname, './src/stores'),
      '@/hooks': path.resolve(__dirname, './src/hooks'),
      '@/types': path.resolve(__dirname, './src/types'),
      '@/api': path.resolve(__dirname, './src/api'),
      '@/utils': path.resolve(__dirname, './src/utils'),
      '@web': path.resolve(__dirname, './src'),
      '@web/types': path.resolve(__dirname, './src/types'),
      '@web/utils': path.resolve(__dirname, './src/utils'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        // Use IPv4 loopback explicitly to avoid localhost->::1 resolution issues
        // when backend binds only 127.0.0.1 (which causes Axios "Network Error").
        target: 'http://127.0.0.1:8012',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist'
  }
})
