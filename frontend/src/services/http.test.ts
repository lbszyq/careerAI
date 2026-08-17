import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiClientError, registerUnauthorizedHandler, request, uploadFile } from './http';

const ACCESS_KEY = 'careerai:access_token';
const REFRESH_KEY = 'careerai:refresh_token';

/** 构造统一响应信封对象（http.ts 只用到 status / json()） */
function envelope(code: number, message: string, data: unknown) {
  return { code, message, data };
}

function resp(status: number, body: unknown) {
  return { status, json: async () => body };
}

function tokenPair(access: string, refresh: string) {
  return { access_token: access, refresh_token: refresh, token_type: 'bearer', expires_in: 1800 };
}

const unauthorizedSpy = vi.fn(() => {});

beforeEach(() => {
  localStorage.clear();
  unauthorizedSpy.mockClear();
  registerUnauthorizedHandler(unauthorizedSpy);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('http.ts token 刷新一致性', () => {
  it('request：1003 触发 refresh 并重放成功（带新 access token）', async () => {
    localStorage.setItem(ACCESS_KEY, 'old-access');
    localStorage.setItem(REFRESH_KEY, 'refresh-token');

    const calls: { url: string; authorization?: string }[] = [];
    const fetchMock = vi.fn(async (url: unknown, init?: { headers?: Record<string, string> }) => {
      const u = String(url);
      calls.push({ url: u, authorization: init?.headers?.Authorization });
      if (u.endsWith('/auth/refresh')) {
        return resp(200, envelope(0, 'ok', tokenPair('new-access', 'new-refresh')));
      }
      const profileHits = calls.filter((c) => c.url.endsWith('/profile')).length;
      if (profileHits === 1) return resp(200, envelope(1003, 'token 已过期', null));
      return resp(200, envelope(0, 'ok', { id: 'u1', username: 'alice' }));
    });
    vi.stubGlobal('fetch', fetchMock);

    const data = await request<{ id: string; username: string }>('/profile');

    expect(data).toEqual({ id: 'u1', username: 'alice' });
    const retry = calls.find((c) => c.url.endsWith('/profile') && c.authorization === 'Bearer new-access');
    expect(retry).toBeDefined();
    expect(localStorage.getItem(ACCESS_KEY)).toBe('new-access');
    expect(calls.filter((c) => c.url.endsWith('/auth/refresh')).length).toBe(1);
  });

  it('uploadFile：1003 触发 refresh 并重放成功', async () => {
    localStorage.setItem(ACCESS_KEY, 'old-access');
    localStorage.setItem(REFRESH_KEY, 'refresh-token');

    const calls: { url: string; authorization?: string }[] = [];
    const fetchMock = vi.fn(async (url: unknown, init?: { headers?: Record<string, string> }) => {
      const u = String(url);
      calls.push({ url: u, authorization: init?.headers?.Authorization });
      if (u.endsWith('/auth/refresh')) {
        return resp(200, envelope(0, 'ok', tokenPair('new-access', 'new-refresh')));
      }
      const uploadHits = calls.filter((c) => c.url.endsWith('/profile/resume')).length;
      if (uploadHits === 1) return resp(200, envelope(1003, 'token 已过期', null));
      return resp(200, envelope(0, 'ok', { task_id: 't1', status: 'pending' }));
    });
    vi.stubGlobal('fetch', fetchMock);

    const formData = new FormData();
    formData.append('file', 'resume-content');
    const data = await uploadFile<{ task_id: string; status: string }>('/profile/resume', formData);

    expect(data).toEqual({ task_id: 't1', status: 'pending' });
    const retry = calls.find((c) => c.url.endsWith('/profile/resume') && c.authorization === 'Bearer new-access');
    expect(retry).toBeDefined();
    expect(localStorage.getItem(ACCESS_KEY)).toBe('new-access');
  });

  it('request：1001 不触发 refresh，直接清 token 并触发登录弹窗', async () => {
    localStorage.setItem(ACCESS_KEY, 'old-access');
    localStorage.setItem(REFRESH_KEY, 'refresh-token');

    const fetchMock = vi.fn(async () => resp(200, envelope(1001, '未登录', null)));
    vi.stubGlobal('fetch', fetchMock);

    await expectCode(request('/profile'), 1001);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(unauthorizedSpy).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(ACCESS_KEY)).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it('uploadFile：1001 不触发 refresh，直接清 token 并触发登录弹窗', async () => {
    localStorage.setItem(ACCESS_KEY, 'old-access');
    localStorage.setItem(REFRESH_KEY, 'refresh-token');

    const fetchMock = vi.fn(async () => resp(200, envelope(1001, '未登录', null)));
    vi.stubGlobal('fetch', fetchMock);

    const formData = new FormData();
    formData.append('file', 'resume-content');
    await expectCode(uploadFile('/profile/resume', formData), 1001);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(unauthorizedSpy).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(ACCESS_KEY)).toBeNull();
  });

  it('并发多个 1003 只发一次 refresh（单飞）', async () => {
    localStorage.setItem(ACCESS_KEY, 'old-access');
    localStorage.setItem(REFRESH_KEY, 'refresh-token');

    let refreshHits = 0;
    let profileHits = 0;
    const fetchMock = vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.endsWith('/auth/refresh')) {
        refreshHits += 1;
        return resp(200, envelope(0, 'ok', tokenPair('new-access', 'new-refresh')));
      }
      profileHits += 1;
      if (profileHits <= 2) return resp(200, envelope(1003, 'token 已过期', null));
      return resp(200, envelope(0, 'ok', { id: 'u' + profileHits }));
    });
    vi.stubGlobal('fetch', fetchMock);

    const [a, b] = await Promise.all([
      request<{ id: string }>('/profile'),
      request<{ id: string }>('/profile'),
    ]);

    expect(a.id).toBeDefined();
    expect(b.id).toBeDefined();
    expect(refreshHits).toBe(1);
    expect(profileHits).toBe(4);
  });

  it('request：1003 refresh 失败后 notifyUnauthorized（清 token + 登录弹窗）', async () => {
    localStorage.setItem(ACCESS_KEY, 'old-access');
    localStorage.setItem(REFRESH_KEY, 'refresh-token');

    const fetchMock = vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.endsWith('/auth/refresh')) return resp(200, envelope(1003, 'refresh token 已过期', null));
      return resp(200, envelope(1003, 'token 已过期', null));
    });
    vi.stubGlobal('fetch', fetchMock);

    await expectCode(request('/profile'), 1003);

    expect(unauthorizedSpy).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(ACCESS_KEY)).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it('uploadFile：1003 refresh 失败后 notifyUnauthorized', async () => {
    localStorage.setItem(ACCESS_KEY, 'old-access');
    localStorage.setItem(REFRESH_KEY, 'refresh-token');

    const fetchMock = vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.endsWith('/auth/refresh')) return resp(200, envelope(1003, 'refresh token 已过期', null));
      return resp(200, envelope(1003, 'token 已过期', null));
    });
    vi.stubGlobal('fetch', fetchMock);

    const formData = new FormData();
    formData.append('file', 'resume-content');
    await expectCode(uploadFile('/profile/resume', formData), 1003);

    expect(unauthorizedSpy).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem(ACCESS_KEY)).toBeNull();
  });

  it('retryOnAuth=false 的 1001 仅抛错，不触发登录弹窗（登录/注册）', async () => {
    const fetchMock = vi.fn(async () => resp(200, envelope(1001, '用户名或密码错误', null)));
    vi.stubGlobal('fetch', fetchMock);

    await expectCode(
      request('/auth/login', { method: 'POST', body: { account: 'a', password: 'b' }, retryOnAuth: false }),
      1001,
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(unauthorizedSpy).not.toHaveBeenCalled();
  });
});

async function expectCode(promise: Promise<unknown>, code: number): Promise<void> {
  let caught: unknown = null;
  try {
    await promise;
  } catch (e) {
    caught = e;
  }
  expect(caught).toBeInstanceOf(ApiClientError);
  expect((caught as ApiClientError).code).toBe(code);
}
