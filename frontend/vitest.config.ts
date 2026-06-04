import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { configDefaults, defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    css: false,
    // Vitest runs `__tests__/**` (Vitest) only. Playwright specs under `e2e/**`
    // are collected by Playwright, not Vitest — excluding them here prevents
    // Vitest from trying to transform/run the Playwright golden-path spec.
    // Spread configDefaults.exclude so we keep node_modules/dist/etc. excluded.
    exclude: [...configDefaults.exclude, '**/e2e/**'],
  },
});
