/**
 * PULSAR — ESLint (plan item 8.21).
 *
 * The project had `tsc --noEmit` (types) and ruff (Python lint) but no lint for
 * the TypeScript itself, so the class of bug tsc cannot see — an unused import,
 * a missing hook dependency, a `console.log` left in a money path — had no gate.
 *
 * The rule set is deliberately narrow: correctness rules that catch real
 * mistakes, not style. A lint gate that fires on formatting gets disabled.
 */
import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default tseslint.config(
  {
    ignores: [
      'dist',
      'node_modules',
      'coverage',
      'contracts/lib',
      // Python side: ruff owns it, and the venv is not our source.
      '.venv',
      'api',
      'scripts',
      'tests',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser, ...globals.es2021 },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      // The two rules that catch real React bugs.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // Unused code is dead weight; `_`-prefixed names are deliberate.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrors: 'none' },
      ],
      // `any` at a Firestore/wallet boundary is a real trade-off, not a bug.
      '@typescript-eslint/no-explicit-any': 'off',
      // Empty catch blocks are deliberate in this codebase (best-effort paths);
      // they must still be commented, which the rule below cannot check, so it
      // is off rather than noisy.
      'no-empty': 'off',
    },
  },
  {
    files: ['**/*.test.{ts,tsx}', 'src/test/**'],
    rules: { '@typescript-eslint/no-unused-vars': 'off' },
  },
  {
    // The contract compile gate is a Node script, not browser code.
    files: ['contracts/**/*.js'],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    // public/sw.js runs in a ServiceWorkerGlobalScope, not a window: `self`,
    // `caches`, `clients` and `fetch` are its globals, and the browser config
    // does not know them. Scoped to that file so the rest of the app keeps the
    // strict set — a service worker is the one place where a global typo is
    // silent and the cache is the thing that breaks.
    files: ['public/sw.js'],
    languageOptions: {
      globals: {
        self: 'readonly',
        caches: 'readonly',
        clients: 'readonly',
        fetch: 'readonly',
        URL: 'readonly',
      },
    },
  },
);
