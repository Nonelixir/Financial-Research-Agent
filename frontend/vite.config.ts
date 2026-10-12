import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': new URL('./src', import.meta.url).pathname } },
  build: {
    outDir: '../src/finagent/static/workspace', emptyOutDir: true,
    rollupOptions: { output: { manualChunks: {
      assistant: ['@assistant-ui/react'], markdown: ['react-markdown','remark-gfm','rehype-highlight'],
    } } },
  },
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
});
