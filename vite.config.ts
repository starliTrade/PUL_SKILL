import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
        'cross-fetch': path.resolve(__dirname, 'src/shims/cross-fetch.ts'),
      },
    },
      server: {
    port: 3000,
    strictPort: true,
    host: true,
    allowedHosts: true,
  },
  };
});
