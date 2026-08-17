/* 路由级懒加载回归测试— 防 flaky 加固：冷缓存/并行负载下动态 import 可能明显变慢 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConfigProvider, App as AntApp } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from './App';
import { AuthProvider } from './stores/AuthProvider';
import { LoginModalProvider } from './hooks/LoginModalProvider';

/* ：懒加载等待策略
   - 固定 15s 在首次冷启动/多文件并行负载下偶发超时（回报 BL-009）；
     等待上限提到 30s，用例级超时给到 60s，为等待上限留出渲染/断言余量。
   - 均为有限值，慢 chunk 也不会无限挂起；正常路径耗时不变（首例约 11s）。*/
const LAZY_LOAD_TIMEOUT = 30_000;
const LAZY_POLL_INTERVAL = 500;
const LAZY_TEST_TIMEOUT = 60_000;

async function waitForLazyLoaded(assert: () => void): Promise<void> {
  await waitFor(assert, {
    timeout: LAZY_LOAD_TIMEOUT,
    interval: LAZY_POLL_INTERVAL,
  });
}

function renderApp(initialPath = '/') {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <AntApp>
          <AuthProvider>
            <LoginModalProvider>
              <MemoryRouter initialEntries={[initialPath]}>
                <App />
              </MemoryRouter>
            </LoginModalProvider>
          </AuthProvider>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>,
  );
}

describe('App 路由级懒加载', () => {
  it('懒加载期间显示 Suspense fallback，完成后消失并渲染首页', async () => {
    renderApp('/');
    expect(screen.getByRole('status', { name: '页面加载中' })).toBeInTheDocument();
    await waitForLazyLoaded(() => {
      expect(screen.getByRole('button', { name: /开始我的职业分析/ })).toBeInTheDocument();
    });
    expect(screen.queryByRole('status', { name: '页面加载中' })).not.toBeInTheDocument();
  }, LAZY_TEST_TIMEOUT);

  it('重型报告页路由可达（/report/portrait 懒加载渲染）', async () => {
    renderApp('/report/portrait');
    await waitForLazyLoaded(() => {
      expect(screen.getByText('缺少报告 ID')).toBeInTheDocument();
    });
    expect(screen.queryByRole('status', { name: '页面加载中' })).not.toBeInTheDocument();
  }, LAZY_TEST_TIMEOUT);

  it('未知路由回退首页而非白屏（路由行为回归）', async () => {
    renderApp('/no-such-route');
    await waitForLazyLoaded(() => {
      expect(screen.getByRole('button', { name: /开始我的职业分析/ })).toBeInTheDocument();
    });
  }, LAZY_TEST_TIMEOUT);
});
/* ============================================================
   登录/注册流程集成测试（任务标准 1 之①）
   - 登录成功/失败（1001 统一文案）、注册成功/失败（2001 映射文案）
   - Modal 打开/关闭开关控制
   依赖注入：全局 mock fetch（auth/reports 端点），不依赖真实后端
   注：登录/注册请求走 authApi（retryOnAuth:false），1001 不触发全局登出回调
   ============================================================ */
describe('登录/注册流程', () => {
  const user = { id: 'u1', username: 'alice', phone: null, role: 'user', created_at: '2026-08-14T10:00:00' };
  const tokens = { access_token: 'acc-token', refresh_token: 'ref-token', token_type: 'bearer', expires_in: 1800 };

  const envelope = (code: number, message: string, data: unknown) => ({
    status: 200,
    json: async () => ({ code, message, data }),
  });

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    const fetchMock = vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.includes('/auth/login')) {
        return envelope(0, 'ok', { user, tokens });
      }
      if (u.includes('/auth/register')) {
        return envelope(0, 'ok', { user: { ...user, username: 'bob' }, tokens });
      }
      // 登录后 HomePage 拉取报告列表（空列表）
      if (u.includes('/reports')) {
        return envelope(0, 'ok', { total: 0, page: 1, page_size: 1, items: [] });
      }
      return envelope(0, 'ok', null);
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('登录成功：Modal 关闭、显示用户名、仪表盘渲染（正向）', async () => {
    renderApp('/');
    await userEvent.click(screen.getByRole('button', { name: /登\s*录/ }));

    const dialog = await screen.findByRole('dialog', {}, { timeout: 15000 });
    await userEvent.type(within(dialog).getByPlaceholderText('用户名或手机号'), 'alice');
    await userEvent.type(within(dialog).getByPlaceholderText('请输入密码'), 'secret123');
    await userEvent.click(within(dialog).getByRole('button', { name: /登\s*录/ }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByText(/你好，alice，欢迎回来/, {}, { timeout: 15000 })).toBeInTheDocument();
  });

  it('登录失败（1001）：Modal 内展示统一错误文案且不关闭（异常）', async () => {
    const fetchMock = vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.includes('/auth/login')) {
        return envelope(1001, '账号或密码错误', null);
      }
      return envelope(0, 'ok', null);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderApp('/');
    await userEvent.click(screen.getByRole('button', { name: /登\s*录/ }));

    const dialog = await screen.findByRole('dialog', {}, { timeout: 15000 });
    await userEvent.type(within(dialog).getByPlaceholderText('用户名或手机号'), 'alice');
    await userEvent.type(within(dialog).getByPlaceholderText('请输入密码'), 'wrong');
    await userEvent.click(within(dialog).getByRole('button', { name: /登\s*录/ }));

    expect(await screen.findByText('账号或密码错误')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('注册成功：自动登录、Modal 关闭、显示新用户名（正向）', async () => {
    renderApp('/');
    await userEvent.click(screen.getByRole('button', { name: /登\s*录/ }));

    const dialog = await screen.findByRole('dialog', {}, { timeout: 15000 });
    await userEvent.click(within(dialog).getByRole('tab', { name: /注\s*册/ }));
    await userEvent.type(within(dialog).getByPlaceholderText('设置用户名（3-64 位）'), 'bob');
    await userEvent.type(within(dialog).getByPlaceholderText('设置密码（至少 8 位）'), 'password123');
    await userEvent.type(within(dialog).getByPlaceholderText('再次输入密码'), 'password123');
    await userEvent.click(within(dialog).getByRole('button', { name: /注\s*册/ }));

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByText(/你好，bob，欢迎回来/, {}, { timeout: 15000 })).toBeInTheDocument();
  });

  it('注册失败（2001）：Modal 内展示映射文案且不关闭（异常）', async () => {
    const fetchMock = vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.includes('/auth/register')) {
        return envelope(2001, '用户名格式不正确', null);
      }
      return envelope(0, 'ok', null);
    });
    vi.stubGlobal('fetch', fetchMock);

    renderApp('/');
    await userEvent.click(screen.getByRole('button', { name: /登\s*录/ }));

    const dialog = await screen.findByRole('dialog', {}, { timeout: 15000 });
    await userEvent.click(within(dialog).getByRole('tab', { name: /注\s*册/ }));
    await userEvent.type(within(dialog).getByPlaceholderText('设置用户名（3-64 位）'), 'bob');
    await userEvent.type(within(dialog).getByPlaceholderText('设置密码（至少 8 位）'), 'password123');
    await userEvent.type(within(dialog).getByPlaceholderText('再次输入密码'), 'password123');
    await userEvent.click(within(dialog).getByRole('button', { name: /注\s*册/ }));

    expect(await screen.findByText('提交的信息格式有误，请检查后重试')).toBeInTheDocument();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('登录 Modal 打开与关闭开关控制（边界）', async () => {
    renderApp('/');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /登\s*录/ }));
    expect(await screen.findByRole('dialog', {}, { timeout: 15000 })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
