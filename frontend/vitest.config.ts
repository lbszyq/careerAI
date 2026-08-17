import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Vitest 测试配置：jsdom 环境 + Testing Library + antd 兼容 polyfill
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
