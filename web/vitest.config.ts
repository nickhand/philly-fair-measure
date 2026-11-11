import { fileURLToPath } from 'node:url'
import { mergeConfig, defineConfig, configDefaults } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      exclude: [...configDefaults.exclude, 'e2e/**', 'tests/worker-routes.test.mjs'],
      root: fileURLToPath(new URL('./', import.meta.url)),
      // vite-ssg reads import.meta.env, which only exists in modules Vite transforms
      server: { deps: { inline: ['vite-ssg'] } },
    },
  }),
)
