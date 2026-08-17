/* ============================================================
   重评流程 hook
   状态机：idle → inProgress（轮询 GET /tasks/{task_id}）→ idle | failed
   - 恢复：优先计划回显 latest_reassess（pending/running → 轮询；failed → 降级；
     succeeded → 结果入口），辅以 sessionStorage 兜底（后端未回显进行中任务时）
   - 失败：原计划不变，phase=failed，「重试」= 再次 POST /reassessments
   - 轮询成功：通知父级刷新计划（latest_reassess/completion_check/achievements 同步）
   ============================================================ */
import { useCallback, useEffect, useRef, useState } from 'react';
import { feedbackApi } from '../services/feedbackApi';
import { ApiClientError } from '../services/http';
import { toUserMessage } from '../services/errorMapping';
import type { ApiLatestReassess } from '../types';

const REASSESS_TASK_KEY = 'careerai:reassess_task';
export const REASSESS_POLL_INTERVAL_MS = 5000;

export type ReassessPhase = 'idle' | 'inProgress' | 'failed';

export interface UseReassessFlowOptions {
  planId: string;
  latestReassess: ApiLatestReassess | null;
  onPlanChanged: () => void;
  showError: (message: string) => void;
  pollIntervalMs?: number;
}

export interface ReassessFlowState {
  phase: ReassessPhase;
  /** 申请/重试提交中（按钮 loading） */
  requesting: boolean;
  inProgressTaskId: string | null;
  errorMessage: string | null;
  request: () => Promise<void>;
  retry: () => Promise<void>;
}

export function useReassessFlow({ planId, latestReassess, onPlanChanged, showError, pollIntervalMs = REASSESS_POLL_INTERVAL_MS }: UseReassessFlowOptions): ReassessFlowState {
  const [phase, setPhase] = useState<ReassessPhase>('idle');
  const [requesting, setRequesting] = useState(false);
  const [inProgressTaskId, setInProgressTaskId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const phaseRef = useRef<ReassessPhase>(phase);
  phaseRef.current = phase;
  const planIdRef = useRef(planId);
  planIdRef.current = planId;
  const onPlanChangedRef = useRef(onPlanChanged);
  onPlanChangedRef.current = onPlanChanged;
  const showErrorRef = useRef(showError);
  showErrorRef.current = showError;
  const pollIntervalRef = useRef(pollIntervalMs);
  pollIntervalRef.current = pollIntervalMs;

  /** 开始轮询（成功/失败/取消终态时清理 sessionStorage） */
  const startPolling = useCallback((taskId: string) => {
    setPhase('inProgress');
    setInProgressTaskId(taskId);
    setErrorMessage(null);
    sessionStorage.setItem(REASSESS_TASK_KEY, taskId);
  }, []);

  const stopPolling = useCallback(() => {
    sessionStorage.removeItem(REASSESS_TASK_KEY);
    setInProgressTaskId(null);
    setPhase('idle');
  }, []);

  /** POST /reassessments（申请与失败重试共用；进行中防重入） */
  const postReassessment = useCallback(async (): Promise<void> => {
    if (phaseRef.current === 'inProgress' || requesting) return;
    setRequesting(true);
    setErrorMessage(null);
    try {
      const accepted = await feedbackApi.requestReassessment(planIdRef.current);
      startPolling(accepted.task_id);
    } catch (err) {
      if (err instanceof ApiClientError) {
        // 3403 已有进行中任务：以计划回显恢复为准，不做降级提示
        if (err.code !== 3403) showErrorRef.current(toUserMessage(err));
      } else {
        showErrorRef.current('提交失败，请稍后重试');
      }
    } finally {
      setRequesting(false);
    }
  }, [requesting, startPolling]);

  /* 轮询循环：GET /tasks/{task_id}，5s 间隔，终态后停止 */
  useEffect(() => {
    const taskId = inProgressTaskId;
    if (!taskId) return;
    let stopped = false;
    let inFlight = false;

    const poll = async () => {
      if (inFlight || stopped) return;
      inFlight = true;
      try {
        // 走 feedbackApi 门面：mock 模式下由契约 mock 轮询（真实模式 = tasksApi.get）
        const job = await feedbackApi.getTask(taskId);
        if (stopped) return;
        if (job.status === 'succeeded') {
          // 成功：清除进行中标记，刷新计划（latest_reassess/result_ref/completion_check 由回显同步）
          stopPolling();
          onPlanChangedRef.current();
          return;
        }
        if (job.status === 'failed') {
          sessionStorage.removeItem(REASSESS_TASK_KEY);
          setInProgressTaskId(null);
          setPhase('failed');
          setErrorMessage(job.error_message || '重新评估失败，请稍后重试');
          return;
        }
        if (job.status === 'cancelled') {
          stopPolling();
          return;
        }
        // pending/running：继续等待
      } catch {
        // 轮询失败不中断：任务可能仍在后端执行，下轮重试
        if (!stopped) setErrorMessage('网络连接异常，正在重试…');
      } finally {
        inFlight = false;
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), pollIntervalRef.current);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [inProgressTaskId, stopPolling]);

  /* 计划回显驱动恢复：离开页面返回 / 轮询完成刷新后收敛状态 */
  useEffect(() => {
    if (!latestReassess) return;
    if (latestReassess.status === 'pending' || latestReassess.status === 'running') {
      setPhase('inProgress');
      setInProgressTaskId(latestReassess.task_id);
      setErrorMessage(null);
      sessionStorage.setItem(REASSESS_TASK_KEY, latestReassess.task_id);
    } else if (latestReassess.status === 'failed') {
      sessionStorage.removeItem(REASSESS_TASK_KEY);
      setInProgressTaskId(null);
      setPhase('failed');
      setErrorMessage('重新评估失败，请稍后重试');
    } else if (latestReassess.status === 'succeeded' || latestReassess.status === 'cancelled') {
      sessionStorage.removeItem(REASSESS_TASK_KEY);
      setInProgressTaskId(null);
      setPhase('idle');
      setErrorMessage(null);
    }
  }, [latestReassess]);

  /* sessionStorage 兜底：后端未回显进行中任务时恢复轮询 */
  useEffect(() => {
    const saved = sessionStorage.getItem(REASSESS_TASK_KEY);
    if (saved && !latestReassess) {
      startPolling(saved);
    }
    // 仅挂载时执行一次；后续由 latestReassess 回显驱动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    phase,
    requesting,
    inProgressTaskId,
    errorMessage,
    request: postReassessment,
    retry: postReassessment,
  };
}

export { REASSESS_TASK_KEY };
