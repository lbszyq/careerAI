/* ============================================================
   报告等待 hook（/Q3：生成中报告可见与续接）
   列表页生成中卡片点击 → GeneratingPage（?reportId=xxx）→ 本 hook
   轮询 GET /reports 列表（：列表含 pending/running 记录），
   按 reportId 匹配状态；completed 触发 onCompleted，failed 触发 onFailed
   ============================================================ */
import { useEffect, useRef, useState } from 'react';
import { reportsApi } from '../services/reportsApi';
import { ApiClientError } from '../services/http';
import { toUserMessage } from '../services/errorMapping';
import type { ApiReportListItem, ApiReportStatus } from '../types';

export const REPORT_POLL_INTERVAL_MS = 5000;

export interface UseReportWaitingOptions {
  reportId: string | null;
  pollIntervalMs?: number;
  onCompleted?: (item: ApiReportListItem) => void;
  onFailed?: (item: ApiReportListItem) => void;
}

export interface ReportWaitingState {
  status: ApiReportStatus | null;
  loading: boolean;
  error: string | null;
}

/** 轮询报告列表直到目标报告脱离生成中状态 */
export function useReportWaiting({ reportId, pollIntervalMs = REPORT_POLL_INTERVAL_MS, onCompleted, onFailed }: UseReportWaitingOptions): ReportWaitingState {
  const [status, setStatus] = useState<ApiReportStatus | null>(null);
  const [loading, setLoading] = useState(Boolean(reportId));
  const [error, setError] = useState<string | null>(null);

  const reportIdRef = useRef(reportId);
  const onCompletedRef = useRef(onCompleted);
  const onFailedRef = useRef(onFailed);
  const pollIntervalRef = useRef(pollIntervalMs);
  reportIdRef.current = reportId;
  onCompletedRef.current = onCompleted;
  onFailedRef.current = onFailed;
  pollIntervalRef.current = pollIntervalMs;

  useEffect(() => {
    const id = reportIdRef.current;
    if (!id) return;
    let stopped = false;
    let inFlight = false;

    const poll = async () => {
      if (inFlight || stopped) return;
      inFlight = true;
      try {
        const list = await reportsApi.list(1, 50);
        if (stopped) return;
        const item = list.items.find((i) => i.id === id);
        if (!item) {
          // 列表中暂未出现（分页外或后端尚未返回）：保持等待，不视为错误
          setLoading(false);
          return;
        }
        setError(null);
        setLoading(false);
        // 契约新增 status；对未携带 status 的旧后端兜底视为 completed（联调期兼容）
        const resolved = item.status ?? 'completed';
        setStatus(resolved);
        if (resolved === 'completed') {
          onCompletedRef.current?.(item);
        } else if (resolved === 'failed') {
          onFailedRef.current?.(item);
        }
      } catch (err) {
        if (stopped) return;
        setError(err instanceof ApiClientError ? toUserMessage(err) : '报告状态查询失败');
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
    // 仅挂载时启动；后续状态更新通过回调驱动（reportId 由 URL 固定）
  }, []);

  return { status, loading, error };
}
