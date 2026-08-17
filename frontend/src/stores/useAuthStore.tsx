/* ============================================================
   全局登录态 hook 与 Context（阶段二：真实 JWT 会话）
   - useAuth：读取登录态/操作（AuthProvider 提供值）
   ：AuthProvider 已拆至 AuthProvider.tsx（react-refresh 只允许组件文件单独导出组件）
   ============================================================ */
import { createContext, useContext } from 'react';
import type { LoginPayload, RegisterPayload } from '../services/authApi';
import type { ApiUser } from '../types';

interface AuthState {
  isLoggedIn: boolean;
  user: ApiUser | null;
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
  /** 订阅登录态失效（清除后弹登录） */
  onAuthExpired: (handler: () => void) => () => void;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth 必须在 AuthProvider 内使用');
  }
  return ctx;
}
