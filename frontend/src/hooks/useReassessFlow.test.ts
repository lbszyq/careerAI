/* ============================================================
   useReassessFlow 复盘反馈流程测试
   覆盖（任务标准 1 之④）：
   - 发起→轮询→succeeded 结果落盘（onPlanChanged + sessionStorage 清理）
   - failed：phase=failed + 错误文案；cancelled：回 idle（边界）
   - 轮询网络异常不中断、下轮继续（异常）
   - 3403 静默（依赖回显恢复）；其他错误 showError 用户文案
   - 进行中防重入（不重复 POST）
   - latestReassess 回显恢复（running/failed/succeeded）；sessionStorage 兜底
   全部 fake timers + mock feedbackApi，不依赖真实后端/网络
   ============================================================ */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { REASSESS_POLL_INTERVAL_MS, REASSESS_TASK_KEY, useReassessFlow } from './useReassessFlow';
import { feedbackApi } from '../services/feedbackApi';
import { ApiClientError } from '../services/http';
import type { ApiLatestReassess, ApiTaskJob, ApiTaskStatus } from '../types';

vi.mock('../services/feedbackApi', () => ({
  feedbackApi: { requestReassessment: vi.fn(), getTask: vi.fn() },
}));

const requestMock = vi.mocked(feedbackApi.requestReassessment);
const getTaskMock = vi.mocked(feedbackApi.getTask);

function taskJob(id: string, status: ApiTaskStatus, errorMessage: string | null = null): ApiTaskJob {
  return {
    id,
    task_type: 'plan_reassess',
    status,
    progress: 50,
    stage: null,
    result_ref: null,
    result: null,
    error_message: errorMessage,
    created_at: '2026-08-14T10:00:00',
    updated_at: '2026-08-14T10:00:00',
    finished_at: null,
  };
}

function latest(status: ApiTaskStatus): ApiLatestReassess {
  return {
    task_id: 't-latest',
    status,
    result_ref: status === 'succeeded' ? '/api/v1/plans/p1/reassessments/ra1' : null,
    created_at: '2026-08-14T10:00:00',
    finished_at: null,
  };
}

/** 冲刷微任务队列 */
async function flush() {
  await act(async () => {
    await Promise.resolve();
  });
}

function setup(overrides: Partial<Parameters<typeof useReassessFlow>[0]> = {}) {
  return renderHook(() =>
    useReassessFlow({
      planId: 'p1',
      latestReassess: null,
      onPlanChanged: vi.fn(),
      showError: vi.fn(),
      ...overrides,
    }),
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  sessionStorage.clear();
  requestMock.mockReset();
  getTaskMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  sessionStorage.clear();
});

describe('useReassessFlow 复盘流程', () => {
  it('发起复盘→轮询 running→succeeded：结果落盘、onPlanChanged、清理 sessionStorage（正向）', async () => {
    requestMock.mockResolvedValueOnce({ task_id: 't1', status: 'running' });
    getTaskMock.mockResolvedValueOnce(taskJob('t1', 'running')).mockResolvedValueOnce(taskJob('t1', 'succeeded'));
    const onPlanChanged = vi.fn();
    const showError = vi.fn();
    const { result } = renderHook(() =>
      useReassessFlow({ planId: 'p1', latestReassess: null, onPlanChanged, showError }),
    );

    await act(async () => {
      await result.current.request();
    });
    expect(requestMock).toHaveBeenCalledWith('p1');
    expect(result.current.phase).toBe('inProgress');
    expect(result.current.inProgressTaskId).toBe('t1');
    expect(sessionStorage.getItem(REASSESS_TASK_KEY)).toBe('t1');

    // 立即轮询一次（running → 继续等待）
    await flush();
    expect(getTaskMock).toHaveBeenCalledWith('t1');
    expect(result.current.phase).toBe('inProgress');

    // 5s 后第二次轮询 succeeded
    await act(async () => {
      vi.advanceTimersByTime(REASSESS_POLL_INTERVAL_MS);
    });
    expect(result.current.phase).toBe('idle');
    expect(result.current.inProgressTaskId).toBeNull();
    expect(onPlanChanged).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(REASSESS_TASK_KEY)).toBeNull();
    expect(showError).not.toHaveBeenCalled();
  });

  it('轮询 failed：phase=failed、展示任务错误文案、清理 sessionStorage（异常路径）', async () => {
    requestMock.mockResolvedValueOnce({ task_id: 't1', status: 'running' });
    getTaskMock.mockResolvedValueOnce(taskJob('t1', 'failed', 'AI 服务超时'));
    const onPlanChanged = vi.fn();
    const { result } = renderHook(() =>
      useReassessFlow({ planId: 'p1', latestReassess: null, onPlanChanged, showError: vi.fn() }),
    );

    await act(async () => {
      await result.current.request();
    });
    await flush();

    expect(result.current.phase).toBe('failed');
    expect(result.current.errorMessage).toBe('AI 服务超时');
    expect(sessionStorage.getItem(REASSESS_TASK_KEY)).toBeNull();
    expect(onPlanChanged).not.toHaveBeenCalled();
  });

  it('轮询 failed 无 error_message：使用兜底文案（异常路径）', async () => {
    requestMock.mockResolvedValueOnce({ task_id: 't1', status: 'running' });
    getTaskMock.mockResolvedValueOnce(taskJob('t1', 'failed'));
    const { result } = setup();

    await act(async () => {
      await result.current.request();
    });
    await flush();

    expect(result.current.phase).toBe('failed');
    expect(result.current.errorMessage).toBe('重新评估失败，请稍后重试');
  });

  it('轮询 cancelled：回 idle 并清理 sessionStorage，不刷新计划（边界）', async () => {
    requestMock.mockResolvedValueOnce({ task_id: 't1', status: 'running' });
    getTaskMock.mockResolvedValueOnce(taskJob('t1', 'cancelled'));
    const onPlanChanged = vi.fn();
    const { result } = renderHook(() =>
      useReassessFlow({ planId: 'p1', latestReassess: null, onPlanChanged, showError: vi.fn() }),
    );

    await act(async () => {
      await result.current.request();
    });
    await flush();

    expect(result.current.phase).toBe('idle');
    expect(sessionStorage.getItem(REASSESS_TASK_KEY)).toBeNull();
    expect(onPlanChanged).not.toHaveBeenCalled();
  });

  it('轮询网络异常：不中断流程、提示重试、下轮继续轮询（异常）', async () => {
    requestMock.mockResolvedValueOnce({ task_id: 't1', status: 'running' });
    getTaskMock.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce(taskJob('t1', 'succeeded'));
    const onPlanChanged = vi.fn();
    const { result } = renderHook(() =>
      useReassessFlow({ planId: 'p1', latestReassess: null, onPlanChanged, showError: vi.fn() }),
    );

    await act(async () => {
      await result.current.request();
    });
    await flush();
    expect(result.current.errorMessage).toBe('网络连接异常，正在重试…');
    expect(result.current.phase).toBe('inProgress');

    await act(async () => {
      vi.advanceTimersByTime(REASSESS_POLL_INTERVAL_MS);
    });
    expect(result.current.phase).toBe('idle');
    expect(onPlanChanged).toHaveBeenCalledTimes(1);
  });

  it('requestReassessment 返回 3403（已有进行中任务）：静默不弹错误（由回显恢复）', async () => {
    requestMock.mockRejectedValueOnce(new ApiClientError(3403, '该计划已有进行中的重评任务', 409));
    const showError = vi.fn();
    const { result } = renderHook(() =>
      useReassessFlow({ planId: 'p1', latestReassess: null, onPlanChanged: vi.fn(), showError }),
    );

    await act(async () => {
      await result.current.request();
    });

    expect(showError).not.toHaveBeenCalled();
    expect(result.current.phase).toBe('idle');
    expect(result.current.requesting).toBe(false);
  });

  it('requestReassessment 业务错误（3402 前置不满足）：showError 展示用户文案（异常）', async () => {
    requestMock.mockRejectedValueOnce(new ApiClientError(3402, '请先上传成果或标记任务进度', 400));
    const showError = vi.fn();
    const { result } = renderHook(() =>
      useReassessFlow({ planId: 'p1', latestReassess: null, onPlanChanged: vi.fn(), showError }),
    );

    await act(async () => {
      await result.current.request();
    });

    expect(showError).toHaveBeenCalledTimes(1);
    expect(showError).toHaveBeenCalledWith('请先上传成果或标记任务进度');
    expect(result.current.phase).toBe('idle');
  });

  it('进行中防重入：inProgress 期间再次 request 不重复 POST（边界）', async () => {
    requestMock.mockResolvedValue({ task_id: 't1', status: 'running' });
    getTaskMock.mockResolvedValue(taskJob('t1', 'running'));
    const { result } = setup();

    await act(async () => {
      await result.current.request();
    });
    expect(requestMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.request();
    });
    expect(requestMock).toHaveBeenCalledTimes(1);
  });

  it('latestReassess=running：回显恢复轮询（inProgress + sessionStorage + 立即轮询）（正向）', async () => {
    getTaskMock.mockResolvedValue(taskJob('t-latest', 'running'));
    const { result } = setup({ latestReassess: latest('running') });

    await flush();
    expect(result.current.phase).toBe('inProgress');
    expect(result.current.inProgressTaskId).toBe('t-latest');
    expect(sessionStorage.getItem(REASSESS_TASK_KEY)).toBe('t-latest');
    expect(getTaskMock).toHaveBeenCalledWith('t-latest');
  });

  it('latestReassess=failed：phase=failed + 降级文案，不轮询（边界）', () => {
    const { result } = setup({ latestReassess: latest('failed') });
    expect(result.current.phase).toBe('failed');
    expect(result.current.errorMessage).toBe('重新评估失败，请稍后重试');
    expect(getTaskMock).not.toHaveBeenCalled();
  });

  it('latestReassess=succeeded：回 idle 并清理 sessionStorage（边界）', () => {
    sessionStorage.setItem(REASSESS_TASK_KEY, 'stale');
    const { result } = setup({ latestReassess: latest('succeeded') });
    expect(result.current.phase).toBe('idle');
    expect(sessionStorage.getItem(REASSESS_TASK_KEY)).toBeNull();
    expect(getTaskMock).not.toHaveBeenCalled();
  });

  it('sessionStorage 兜底：后端未回显进行中任务时恢复轮询（边界）', async () => {
    sessionStorage.setItem(REASSESS_TASK_KEY, 't3');
    getTaskMock.mockResolvedValue(taskJob('t3', 'running'));
    const { result } = setup();

    await flush();
    expect(result.current.phase).toBe('inProgress');
    expect(result.current.inProgressTaskId).toBe('t3');
    expect(getTaskMock).toHaveBeenCalledWith('t3');
  });
});
