/* ============================================================
   统一 HTTP 封装（services 层基座）
   - baseURL：/api/v1（vite dev proxy → 本地 backend）
   - access token 注入；1003 → refresh 重放；1001 → 直接清 token 弹登录
   - 信封解析：code!=0 抛 ApiClientError；HTTP 层错误统一 6001 兜底
   ============================================================ */
import { tokenStore } from './tokenStore';
import { isUnauthorized, isRefreshable } from './errorMapping';
import type { ApiResponse, ApiTokenPair } from '../types';

export class ApiClientError extends Error {
  code: number;
  httpStatus: number;
  constructor(code: number, message: string, httpStatus: number) {
    super(message);
    this.name = 'ApiClientError';
    this.code = code;
    this.httpStatus = httpStatus;
  }
}

const BASE_URL = '/api/v1';

/** 全局未授权回调（AuthProvider 注册：清除登录态并弹登录） */
let unauthorizedHandler: (() => void) | null = null;
export function registerUnauthorizedHandler(handler: () => void): void {
  unauthorizedHandler = handler;
}

/** refresh 单飞：并发多个 401 时只发起一次刷新 */
let refreshPromise: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  const refreshToken = tokenStore.getRefreshToken();
  if (!refreshToken) return false;
  const resp = await fetch(`${BASE_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  let payload: ApiResponse<ApiTokenPair>;
  try {
    payload = (await resp.json()) as ApiResponse<ApiTokenPair>;
  } catch {
    return false;
  }
  if (payload.code !== 0 || !payload.data) return false;
  tokenStore.saveTokens(payload.data);
  return true;
}

function notifyUnauthorized(): void {
  tokenStore.clear();
  unauthorizedHandler?.();
}

/** refresh 单飞：并发多个 401 时只发起一次刷新 */
async function refreshOnce(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  /** 是否注入 Bearer token（市场公开端点传 false） */
  auth?: boolean;
  /** 是否在 401/1003 时尝试刷新重放 */
  retryOnAuth?: boolean;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, headers = {}, auth = true, retryOnAuth = true } = options;

  const buildHeaders = (): Record<string, string> => {
    const h: Record<string, string> = { ...headers };
    if (body !== undefined) h['Content-Type'] = 'application/json';
    if (auth) {
      const accessToken = tokenStore.getAccessToken();
      if (accessToken) h.Authorization = `Bearer ${accessToken}`;
    }
    return h;
  };

  const doFetch = async (): Promise<{ payload: ApiResponse<unknown>; httpStatus: number }> => {
    const resp = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: buildHeaders(),
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let payload: ApiResponse<unknown>;
    try {
      payload = (await resp.json()) as ApiResponse<unknown>;
    } catch {
      // 非 JSON 响应（网络层错误/网关）统一兜底
      throw new ApiClientError(6001, '服务器响应异常', resp.status);
    }
    return { payload, httpStatus: resp.status };
  };

  try {
    const { payload, httpStatus } = await doFetch();

    if (payload.code === 0) return payload.data as T;

    // 认证失败分流（登录/注册/刷新请求不重放）：
    // 1003（token 过期）→ refresh 重放；1001（未登录/非法）→ refresh 无法恢复，直接清 token 弹登录
    if (retryOnAuth && auth && isUnauthorized(payload.code)) {
      if (isRefreshable(payload.code)) {
        if (tokenStore.getRefreshToken()) {
          const refreshed = await refreshOnce();
          if (refreshed) {
            const retryResult = await doFetch();
            if (retryResult.payload.code === 0) return retryResult.payload.data as T;
            if (isUnauthorized(retryResult.payload.code)) {
              notifyUnauthorized();
            }
            throw new ApiClientError(retryResult.payload.code, retryResult.payload.message, retryResult.httpStatus);
          }
        }
        notifyUnauthorized();
      } else {
        notifyUnauthorized();
      }
    }

    throw new ApiClientError(payload.code, payload.message, httpStatus);
  } catch (err) {
    if (err instanceof ApiClientError) throw err;
    // 网络断开：转为 6001 系统兜底（NetworkBanner 组件负责提示）
    throw new ApiClientError(6001, '网络连接异常，请检查网络', 0);
  }
}

/** 文件上传（multipart/form-data，不走 JSON 序列化） */
export async function uploadFile<T>(path: string, formData: FormData, auth = true): Promise<T> {
  const doUpload = async (): Promise<{ payload: ApiResponse<T>; httpStatus: number }> => {
    const headers: Record<string, string> = {};
    if (auth) {
      const accessToken = tokenStore.getAccessToken();
      if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    }
    const resp = await fetch(`${BASE_URL}${path}`, {
      method: 'POST',
      headers,
      body: formData,
    });
    const payload = (await resp.json()) as ApiResponse<T>;
    return { payload, httpStatus: resp.status };
  };

  try {
    const { payload, httpStatus } = await doUpload();

    if (payload.code === 0) return payload.data as T;

    // 与 request 对齐：1003（token 过期）→ refresh 重放；1001（未登录/非法）→ 直接清 token 弹登录
    if (auth && isUnauthorized(payload.code)) {
      if (isRefreshable(payload.code)) {
        if (tokenStore.getRefreshToken()) {
          const refreshed = await refreshOnce();
          if (refreshed) {
            const retryResult = await doUpload();
            if (retryResult.payload.code === 0) return retryResult.payload.data as T;
            if (isUnauthorized(retryResult.payload.code)) {
              notifyUnauthorized();
            }
            throw new ApiClientError(retryResult.payload.code, retryResult.payload.message, retryResult.httpStatus);
          }
        }
        notifyUnauthorized();
      } else {
        notifyUnauthorized();
      }
    }

    throw new ApiClientError(payload.code, payload.message, httpStatus);
  } catch (err) {
    if (err instanceof ApiClientError) throw err;
    throw new ApiClientError(6001, '网络连接异常，请检查网络', 0);
  }
}
