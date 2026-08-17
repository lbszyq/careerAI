/* ============================================================
   AI 操作状态机（§AI 状态管理 + architecture）
   状态：IDLE → SUBMITTING → PROCESSING/GENERATING → SUCCESS | FAILED | CANCELLED
   - 5s 轮询 GET /tasks/{id}（架构 数据请求：TanStack Query 语义由本 hook 承载）
   - 超时（>180s）触发 timeoutAlert（交互规范）
   - 取消：POST /tasks/{id}/cancel（C-33，取消后不产生报告记录）
   - 离开不取消：taskId 由调用方持久化（sessionStorage），返回恢复轮询
   ============================================================ */
import { useCallback, useEffect, useRef, useState } from 'react';
import { tasksApi } from '../services/tasksApi';
import { ApiClientError } from '../services/http';
import { toUserMessage } from '../services/errorMapping';
import type { ApiTaskJob } from '../types';

export type AiPhase = 'IDLE' | 'SUBMITTING' | 'PROCESSING' | 'GENERATING' | 'SUCCESS' | 'FAILED' | 'CANCELLED';

export const POLL_INTERVAL_MS = 5000;
export const TIMEOUT_MS = 180_000; // 3 分钟（page-03：超过 2-3 分钟触发超时 Alert）

export interface UseAiOperationOptions {
  taskId: string | null;
  stepNames: string[];
  timeoutMs?: number;
  pollIntervalMs?: number;
  onSuccess?: (task: ApiTaskJob) => void;
  onCancelled?: () => void;
}

export type AiStepState = 'pending' | 'running' | 'done';

export interface AiOperationState {
  phase: AiPhase;
  task: ApiTaskJob | null;
  steps: { name: string; state: AiStepState }[];
  percent: number;
  elapsedSeconds: number;
  timeoutAlert: boolean;
  errorMessage: string | null;
  cancelLoading: boolean;
  cancel: () => Promise<void>;
}

/** 将任务 stage 文案（如「职业画像分析」）对齐到生成步骤名称 */
function resolveStageLabel(stage: string | null, stepNames: string[]): string | null {
  if (!stage) return null;
  for (const name of stepNames) {
    if (stage.includes(name) || name.includes(stage)) return name;
  }
  return stage;
}

function buildSteps(task: ApiTaskJob | null, stepNames: string[]): { name: string; state: AiStepState }[] {
  if (!task) {
    return stepNames.map((name, index) => ({ name, state: index === 0 ? 'running' : 'pending' }));
  }
  const progress = Math.max(0, Math.min(100, task.progress ?? 0));
  const total = stepNames.length;
  const doneCount = Math.floor((progress / 100) * total);
  const currentStageLabel = resolveStageLabel(task.stage, stepNames);

  return stepNames.map((name, index) => {
    if (index < doneCount) return { name, state: 'done' };
    if (index === doneCount) {
      return { name: currentStageLabel ?? name, state: 'running' };
    }
    return { name, state: 'pending' };
  });
}

export function useAiOperation({ taskId, stepNames, timeoutMs = TIMEOUT_MS, pollIntervalMs = POLL_INTERVAL_MS, onSuccess, onCancelled }: UseAiOperationOptions) {
  const [phase, setPhase] = useState<AiPhase>(taskId ? 'PROCESSING' : 'IDLE');
  const [task, setTask] = useState<ApiTaskJob | null>(null);
  const [steps, setSteps] = useState<{ name: string; state: AiStepState }[]>(() =>
    stepNames.map((name, index) => ({ name, state: index === 0 ? 'running' : 'pending' })),
  );
  const [percent, setPercent] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [timeoutAlert, setTimeoutAlert] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [cancelLoading, setCancelLoading] = useState(false);

  const taskIdRef = useRef<string | null>(taskId);
  const terminalRef = useRef(!taskId);
  const onSuccessRef = useRef(onSuccess);
  const onCancelledRef = useRef(onCancelled);
  const stepNamesRef = useRef(stepNames);
  const pollIntervalRef = useRef(pollIntervalMs);
  onSuccessRef.current = onSuccess;
  onCancelledRef.current = onCancelled;
  stepNamesRef.current = stepNames;
  pollIntervalRef.current = pollIntervalMs;

  // 轮询循环（仅随 taskId 是否存在启停；终态后停止）
  useEffect(() => {
    if (!taskIdRef.current || terminalRef.current) return;

    let stopped = false;
    let inFlight = false;
    const poll = async () => {
      const id = taskIdRef.current;
      if (!id || inFlight || stopped || terminalRef.current) return;
      inFlight = true;
      try {
        const job = await tasksApi.get(id);
        if (stopped) return;
        setTask(job);
        setPercent(job.progress ?? 0);
        setSteps(buildSteps(job, stepNamesRef.current));
        setErrorMessage(null);

        if (job.status === 'succeeded') {
          terminalRef.current = true;
          setPhase('SUCCESS');
          onSuccessRef.current?.(job);
          return;
        }
        if (job.status === 'failed') {
          terminalRef.current = true;
          setPhase('FAILED');
          setErrorMessage(job.error_message ?? '分析暂时失败，请稍后重试');
          return;
        }
        if (job.status === 'cancelled') {
          terminalRef.current = true;
          setPhase('CANCELLED');
          onCancelledRef.current?.();
          return;
        }
        setPhase((job.progress ?? 0) >= 100 ? 'GENERATING' : 'PROCESSING');
      } catch {
        // 轮询失败不中断：任务可能仍在后端执行，下轮重试；错误由终态或全局 401 处理兜底
        if (!stopped) setErrorMessage('网络连接异常，正在重试…');
      } finally {
        inFlight = false;
      }
    };

    poll();
    const interval = window.setInterval(poll, pollIntervalRef.current);
    const tick = window.setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);
    return () => {
      stopped = true;
      window.clearInterval(interval);
      window.clearInterval(tick);
    };
  }, []);

  // 超时检测（elapsed > timeoutMs 且未终态）
  useEffect(() => {
    if (timeoutMs <= 0 || terminalRef.current || phase === 'IDLE') return;
    if (elapsedSeconds * 1000 >= timeoutMs) setTimeoutAlert(true);
  }, [elapsedSeconds, timeoutMs, phase]);

  // 取消任务
  const cancel = useCallback(async () => {
    const id = taskIdRef.current;
    if (!id || terminalRef.current) return;
    setCancelLoading(true);
    try {
      const result = await tasksApi.cancel(id);
      if (result.status === 'cancelled') {
        terminalRef.current = true;
        setPhase('CANCELLED');
        onCancelledRef.current?.();
      }
    } catch (err) {
      setErrorMessage(err instanceof ApiClientError ? toUserMessage(err) : '取消失败，请稍后重试');
    } finally {
      setCancelLoading(false);
    }
  }, []);

  return { phase, task, steps, percent, elapsedSeconds, timeoutAlert, errorMessage, cancelLoading, cancel };
}
