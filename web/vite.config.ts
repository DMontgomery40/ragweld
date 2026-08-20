import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

function normalizeBuildBase(input: string | undefined): string {
  const raw = String(input || '').trim() || '/web/'
  let normalized = raw.startsWith('/') ? raw : `/${raw}`
  normalized = normalized.replace(/\/{2,}/g, '/')
  if (!normalized.endsWith('/')) normalized += '/'
  return normalized
}

function normalizeApiProxyTarget(input: string | undefined): string {
  const raw = String(input || '').trim() || 'http://127.0.0.1:58012'
  return raw.replace(/\/+$/, '')
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiProxyTarget = normalizeApiProxyTarget(env.VITE_API_PROXY_TARGET)

  return {
    base: normalizeBuildBase(env.VITE_BUILD_BASE),
    plugins: [react()],
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
      port: Number(env.FRONTEND_PORT || 55173),
      strictPort: true,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
    },
  }
})
