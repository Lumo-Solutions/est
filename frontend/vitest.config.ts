import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      // https, not http: __Host-prefixed cookies (app/security/cookies.py)
      // are only settable in a secure context, and jsdom (unlike Chrome)
      // does not special-case localhost.
      environmentOptions: { jsdom: { url: 'https://localhost/' } },
      globals: true,
      setupFiles: ['./src/test/setup.ts'],
      css: true,
      exclude: ['e2e/**', 'node_modules/**'],
    },
  }),
)
