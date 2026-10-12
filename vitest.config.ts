import { defineConfig } from 'vitest/config';
import path from 'path';

/**
 * Vitest configuration (plan item 0.9).
 *
 * The unit tests cover pure logic and the wallet/provider plumbing — the parts
 * where a bug moves money or silently changes identity. Anything that needs a
 * real browser (touch events, layout, a11y) belongs in the Playwright suite
 * (plan item 0.10), not here.
 */
export default defineConfig({
  resolve: {
    alias: [
      { find: '@', replacement: path.resolve(__dirname, '.') },
      {
        find: /^cross-fetch(\/.*)?$/,
        replacement: path.resolve(__dirname, 'src/shims/cross-fetch.ts'),
      },
    ],
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    globals: false,
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text'],
      include: ['src/lib/**', 'src/store/**'],
      // Deliberately no `thresholds` yet: the frontend suite starts small and a
      // floor here would be a number nobody reads. The server ratchet
      // (.coveragerc) is the enforced one; this is raised in phase 4.
    },
  },
});
