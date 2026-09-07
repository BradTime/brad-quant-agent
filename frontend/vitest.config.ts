import { fileURLToPath } from 'url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['./vitest.setup.ts'],
    // Node 22+ 在未提供 --localstorage-file 时会对 global localStorage 打 ExperimentalWarning；
    // setup 已注入内存 polyfill，此处关掉该噪声。
    onConsoleLog(log) {
      if (log.includes('localStorage is not available')) return false;
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
});
