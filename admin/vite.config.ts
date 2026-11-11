/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The console is a static single-page app: no server code, no secrets in the bundle. Only
// VITE_* variables reach the browser, and they are public by design (API URL, Firebase web key).
export default defineConfig({
  plugins: [react()],
  build: {
    target: 'es2022',
    sourcemap: false,
  },
  server: {
    port: 5180,
    strictPort: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    restoreMocks: true,
  },
});
