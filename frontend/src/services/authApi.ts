/* ============================================================
   auth API（auth-contract，4 端点）
   ============================================================ */
import { request } from './http';
import type { ApiAuthResult, ApiTokenPair, ApiUser } from '../types';

export interface RegisterPayload {
  username: string;
  phone?: string;
  password: string;
}

export interface LoginPayload {
  account: string;
  password: string;
}

export const authApi = {
  /** POST /auth/register：注册即登录，返回 user + tokens */
  register(payload: RegisterPayload): Promise<ApiAuthResult> {
    return request<ApiAuthResult>('/auth/register', { method: 'POST', body: payload, retryOnAuth: false });
  },
  /** POST /auth/login：账号密码登录 */
  login(payload: LoginPayload): Promise<ApiAuthResult> {
    return request<ApiAuthResult>('/auth/login', { method: 'POST', body: payload, retryOnAuth: false });
  },
  /** POST /auth/refresh：refresh token 换新 token 对 */
  refresh(refreshToken: string): Promise<ApiTokenPair> {
    return request<ApiTokenPair>('/auth/refresh', { method: 'POST', body: { refresh_token: refreshToken }, retryOnAuth: false });
  },
  /** GET /auth/me：当前用户 */
  me(): Promise<ApiUser> {
    return request<ApiUser>('/auth/me');
  },
};
