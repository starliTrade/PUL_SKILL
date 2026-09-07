import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: [
        { find: '@', replacement: path.resolve(__dirname, '.') },
        { find: /^cross-fetch(\/.*)?$/, replacement: path.resolve(__dirname, 'src/shims/cross-fetch.ts') },
      ],
    },
    optimizeDeps: {
      exclude: ['cross-fetch'],
    },
    server: {
        port: 3000,
        strictPort: true,
        host: '0.0.0.0',
        allowedHosts: true as const,
      },
  };
});
