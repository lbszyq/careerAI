/* ============================================================
   登录 Modal 全局控制（决策①：登录 = Modal 弹窗）
   任何页面可调用 openLogin() 弹出登录
   ：LoginModalProvider 已拆至 LoginModalProvider.tsx（react-refresh 只允许组件文件单独导出组件）
   ============================================================ */
import { createContext, useContext } from 'react';

interface LoginModalState {
  open: boolean;
  openLogin: () => void;
  closeLogin: () => void;
}

export const LoginModalContext = createContext<LoginModalState | null>(null);

export function useLoginModal(): LoginModalState {
  const ctx = useContext(LoginModalContext);
  if (!ctx) {
    throw new Error('useLoginModal 必须在 LoginModalProvider 内使用');
  }
  return ctx;
}
