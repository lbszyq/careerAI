/* 全局登录态 Provider（阶段二：真实 JWT 会话）
   - 初始化从 localStorage 恢复（刷新不丢登录态）
   - login/register 走真实 API（auth-contract）
   - 401/1003 由 http 层触发 unauthorizedHandler → 清登录态 + 广播 authExpired
   ：从 useAuthStore.tsx 拆出组件文件，消除 react-refresh 混合导出警告 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { authApi, type LoginPayload, type RegisterPayload } from '../services/authApi';
import { tokenStore } from '../services/tokenStore';
import { registerUnauthorizedHandler } from '../services/http';
import type { ApiUser } from '../types';
import { AuthContext } from './useAuthStore';

const expiryListeners = new Set<() => void>();

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(() => tokenStore.getUser());

  const isLoggedIn = useMemo(() => Boolean(user) && Boolean(tokenStore.getAccessToken()), [user]);

  const login = useCallback(async (payload: LoginPayload) => {
    const result = await authApi.login(payload);
    tokenStore.save(result.tokens, result.user);
    setUser(result.user);
  }, []);

  const register = useCallback(async (payload: RegisterPayload) => {
    const result = await authApi.register(payload);
    tokenStore.save(result.tokens, result.user);
    setUser(result.user);
  }, []);

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  const refreshMe = useCallback(async () => {
    const me = await authApi.me();
    setUser(me);
  }, []);

  const onAuthExpired = useCallback((handler: () => void) => {
    expiryListeners.add(handler);
    return () => {
      expiryListeners.delete(handler);
    };
  }, []);

  // 注册 http 层 401 处理器：清除登录态并广播 authExpired
  useEffect(() => {
    registerUnauthorizedHandler(() => {
      tokenStore.clear();
      setUser(null);
      expiryListeners.forEach((fn) => fn());
    });
  }, []);

  const value = useMemo(
    () => ({ isLoggedIn, user, login, register, logout, refreshMe, onAuthExpired }),
    [isLoggedIn, user, login, register, logout, refreshMe, onAuthExpired],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
