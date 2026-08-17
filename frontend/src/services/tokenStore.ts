/* ============================================================
   JWT 会话持久化（localStorage）
   - access_token / refresh_token / 用户信息
   - 登录态刷新不丢（验证标准①）
   ============================================================ */
import type { ApiTokenPair, ApiUser } from '../types';

const ACCESS_KEY = 'careerai:access_token';
const REFRESH_KEY = 'careerai:refresh_token';
const USER_KEY = 'careerai:user';

export const tokenStore = {
  getAccessToken(): string | null {
    return localStorage.getItem(ACCESS_KEY);
  },
  getRefreshToken(): string | null {
    return localStorage.getItem(REFRESH_KEY);
  },
  getUser(): ApiUser | null {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as ApiUser;
    } catch {
      return null;
    }
  },
  save(tokens: ApiTokenPair, user: ApiUser): void {
    localStorage.setItem(ACCESS_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  saveTokens(tokens: ApiTokenPair): void {
    localStorage.setItem(ACCESS_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
  },
  clear(): void {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

/** 会话态表单草稿（：未登录填写 → 登录后不丢失） */
const DRAFT_KEY = 'careerai:profile_draft';
export const draftStore = {
  get(): Record<string, unknown> | null {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return null;
    }
  },
  save(values: Record<string, unknown>): void {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(values));
  },
  clear(): void {
    localStorage.removeItem(DRAFT_KEY);
  },
};
