/* 登录 Modal 全局 Provider（决策①：登录 = Modal 弹窗）
   ：从 useLoginModal.tsx 拆出组件文件，消除 react-refresh 混合导出警告 */
import { useCallback, useMemo, useState, type ReactNode } from 'react';
import { LoginModalContext } from './useLoginModal';

export function LoginModalProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  const openLogin = useCallback(() => setOpen(true), []);
  const closeLogin = useCallback(() => setOpen(false), []);

  const value = useMemo(() => ({ open, openLogin, closeLogin }), [open, openLogin, closeLogin]);

  return <LoginModalContext.Provider value={value}>{children}</LoginModalContext.Provider>;
}
