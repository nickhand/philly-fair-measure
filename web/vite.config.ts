import { fileURLToPath, URL } from 'node:url'
import { existsSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import type {} from 'vite-ssg'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  // production builds are served under a subpath of nickhand.dev (the same
  // pattern as the gun-violence dashboard); dev stays at the root
  base: process.env.VITE_PUBLIC_BASE || '/',
  plugins: [vue(), vueDevTools(), tailwindcss(), {
    name: 'fair-measure-preview-fallback',
    configurePreviewServer(server) {
      // Match production's separate SPA shell for routes without generated HTML.
      server.middlewares.use((req, _res, next) => {
        const pathname = new URL(req.url ?? '/', 'http://localhost').pathname
        const base = server.config.base
        if (pathname.startsWith(base)) {
          const path = pathname.slice(base.length).replace(/\/$/, '')
          if (path && !/\.[a-z0-9]+$/i.test(path) &&
              !existsSync(join(server.config.root, server.config.build.outDir, `${path}.html`))) {
            req.url = `${base}spa.html`
          }
        }
        next()
      })
    },
  }],
  ssgOptions: {
    dirStyle: 'flat',
    includedRoutes(_paths, routes) {
      return routes.filter((route) => route.meta?.prerender).flatMap((route) => [
        route.path,
        ...(typeof route.alias === 'string' ? [route.alias] : route.alias ?? []),
      ])
    },
    onBeforePageRender(route, html) {
      if (route === '/') {
        // Preserve the empty Vite shell before SSG replaces index.html with Home.
        writeFileSync(fileURLToPath(new URL('./dist/spa.html', import.meta.url)), html)
      }
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // the Python API: `uv run fair-measure api` from the repo root
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
