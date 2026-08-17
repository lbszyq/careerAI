// Vitest 全局测试环境初始化
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// 非 globals 模式下 RTL 无法自动注册 cleanup，手动清理避免 DOM 跨用例累积
afterEach(() => {
  cleanup();
});

// antd v5 响应式组件（Grid/Result 等）在 jsdom 下依赖 window.matchMedia
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}
