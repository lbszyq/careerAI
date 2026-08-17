/* ============================================================
   useReportWaiting 报告轮询状态机测试
   覆盖（任务标准 1 之②）：
   - pending→running→succeeded / failed 状态迁移与回调
   - 轮询间隔（默认 5s / 自定义）
   - 边界 ：列表中暂未出现保持等待；旧后端缺 status 字段按 completed 兜底
   - 异常 ：ApiClientError 映射用户文案；普通异常兜底文案
   - 清理：卸载停止轮询；reportId 为空不启动
   全部使用 fake timers，不依赖真实后端/网络
   ============================================================ */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { REPORT_POLL_INTERVAL_MS, useReportWaiting } from './useReportWaiting';
import { reportsApi } from '../services/reportsApi';
import { ApiClientError } from '../services/http';
import type { ApiReportListItem, ApiReportList, ApiReportStatus } from '../types';

vi.mock('../services/reportsApi', () => ({
  reportsApi: { list: vi.fn() },
}));

const listMock = vi.mocked(reportsApi.list);

function item(id: string, status: ApiReportStatus): ApiReportListItem {
  return {
    id,
    stage: 'stage1',
    status,
    score: null,
    created_at: '2026-08-14T10:00:00',
    summary: { job_titles: ['前端工程师'] },
  };
}

function listWith(id: string, status: ApiReportStatus): ApiReportList {
  return { total: 1, page: 1, page_size: 50, items: [item(id, status)] };
}

function emptyList(): ApiReportList {
  return { total: 0, page: 1, page_size: 50, items: [] };
}

/** 冲刷微任务队列，让已 resolve 的 mock 继续执行并提交状态更新 */
async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  listMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useReportWaiting 报告轮询状态机', () => {
  it('pending→running→succeeded 状态迁移，onCompleted 收到完成项（正向）', async () => {
    listMock
      .mockResolvedValueOnce(listWith('r1', 'pending'))
      .mockResolvedValueOnce(listWith('r1', 'running'))
      .mockResolvedValueOnce(listWith('r1', 'completed'));
    const onCompleted = vi.fn();
    const onFailed = vi.fn();
    const { result } = renderHook(() => useReportWaiting({ reportId: 'r1', onCompleted, onFailed }));

    await flush();
    expect(result.current.status).toBe('pending');
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();

    await act(async () => {
      vi.advanceTimersByTime(REPORT_POLL_INTERVAL_MS);
    });
    expect(result.current.status).toBe('running');

    await act(async () => {
      vi.advanceTimersByTime(REPORT_POLL_INTERVAL_MS);
    });
    expect(result.current.status).toBe('completed');
    expect(onCompleted).toHaveBeenCalledTimes(1);
    expect(onCompleted).toHaveBeenCalledWith(expect.objectContaining({ id: 'r1', status: 'completed' }));
    expect(onFailed).not.toHaveBeenCalled();
  });

  it('pending→running→failed 迁移，onFailed 回调且状态落为 failed（异常路径）', async () => {
    listMock
      .mockResolvedValueOnce(listWith('r1', 'running'))
      .mockResolvedValueOnce(listWith('r1', 'failed'));
    const onFailed = vi.fn();
    const onCompleted = vi.fn();
    const { result } = renderHook(() => useReportWaiting({ reportId: 'r1', onFailed, onCompleted }));

    await flush();
    expect(result.current.status).toBe('running');

    await act(async () => {
      vi.advanceTimersByTime(REPORT_POLL_INTERVAL_MS);
    });
    expect(result.current.status).toBe('failed');
    expect(onFailed).toHaveBeenCalledTimes(1);
    expect(onFailed).toHaveBeenCalledWith(expect.objectContaining({ id: 'r1', status: 'failed' }));
    expect(onCompleted).not.toHaveBeenCalled();
  });

  it('按默认 5s 间隔轮询：挂载即 1 次 + 每间隔 1 次，列表请求参数为 (1, 50)', async () => {
    listMock.mockResolvedValue(listWith('r1', 'pending'));
    renderHook(() => useReportWaiting({ reportId: 'r1' }));

    await flush();
    expect(listMock).toHaveBeenCalledTimes(1);
    expect(listMock).toHaveBeenCalledWith(1, 50);

    await act(async () => {
      vi.advanceTimersByTime(REPORT_POLL_INTERVAL_MS);
    });
    expect(listMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      vi.advanceTimersByTime(REPORT_POLL_INTERVAL_MS);
    });
    expect(listMock).toHaveBeenCalledTimes(3);
  });

  it('自定义 pollIntervalMs 生效（1s 间隔，5s 内 6 次）', async () => {
    listMock.mockResolvedValue(listWith('r1', 'pending'));
    renderHook(() => useReportWaiting({ reportId: 'r1', pollIntervalMs: 1000 }));

    await flush();
    expect(listMock).toHaveBeenCalledTimes(1);

    // 步进推进（一次性推进会因 inFlight 防重入跳过中间轮询，需每步冲刷微任务）
    for (let i = 0; i < 5; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
    }
    expect(listMock).toHaveBeenCalledTimes(6);
  });

  it('列表中暂未出现目标报告：保持等待、不报错、不触发回调（边界）', async () => {
    listMock.mockResolvedValue(emptyList());
    const onCompleted = vi.fn();
    const onFailed = vi.fn();
    const { result } = renderHook(() => useReportWaiting({ reportId: 'r1', onCompleted, onFailed }));

    await flush();
    expect(result.current.status).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(onCompleted).not.toHaveBeenCalled();
    expect(onFailed).not.toHaveBeenCalled();
  });

  it('列表项缺 status 字段（旧后端兼容）：按 completed 处理并回调（边界）', async () => {
    const legacy = { ...item('r1', 'pending'), status: undefined } as unknown as ApiReportListItem;
    listMock.mockResolvedValueOnce({ total: 1, page: 1, page_size: 50, items: [legacy] });
    const onCompleted = vi.fn();
    const { result } = renderHook(() => useReportWaiting({ reportId: 'r1', onCompleted }));

    await flush();
    expect(result.current.status).toBe('completed');
    expect(onCompleted).toHaveBeenCalledTimes(1);
    expect(onCompleted).toHaveBeenCalledWith(expect.objectContaining({ id: 'r1' }));
  });

  it('轮询异常：ApiClientError 映射为用户文案，普通异常兜底文案（异常）', async () => {
    listMock
      .mockRejectedValueOnce(new ApiClientError(6001, '系统繁忙', 500))
      .mockRejectedValueOnce(new Error('network down'));
    const { result } = renderHook(() => useReportWaiting({ reportId: 'r1' }));

    await flush();
    expect(result.current.error).toBe('系统繁忙，请稍后再试');

    await act(async () => {
      vi.advanceTimersByTime(REPORT_POLL_INTERVAL_MS);
    });
    expect(result.current.error).toBe('报告状态查询失败');
  });

  it('卸载后停止轮询并清理定时器（清理）', async () => {
    listMock.mockResolvedValue(listWith('r1', 'pending'));
    const { unmount } = renderHook(() => useReportWaiting({ reportId: 'r1' }));

    await flush();
    expect(listMock).toHaveBeenCalledTimes(1);

    unmount();
    await act(async () => {
      vi.advanceTimersByTime(REPORT_POLL_INTERVAL_MS * 5);
    });
    expect(listMock).toHaveBeenCalledTimes(1);
  });

  it('reportId 为空时不启动轮询', async () => {
    renderHook(() => useReportWaiting({ reportId: null }));
    await flush();
    expect(listMock).not.toHaveBeenCalled();
  });
});
