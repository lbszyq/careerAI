/* Page-03 生成中过渡页（体验核心）
    决策④：单页组件双形态——Stage 1 画像 / Stage 2 方向（差距计划），仅步骤文案不同
   阶段二：真实任务轮询（useAiOperation）：
   - 5s 轮询 GET /tasks/{task_id}（进度/步骤来自任务状态）
   - succeeded → 按 result_ref 跳报告页；failed → ErrorState + 重试
   - 超时（>3min）→ 超时 Alert（继续等待/取消生成）；取消 → 确认弹窗 → POST cancel → 返回个人信息页
   - 离开不取消：task_id 存 sessionStorage，返回本页可恢复（C-33） */
import { useCallback, useEffect, useMemo } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Alert, App as AntApp, Button, Card, Modal as AntModal, Spin } from 'antd';
import { ArrowUpOutlined } from '@ant-design/icons';
import GenProgress from '../components/ui/GenProgress';
import DataNote from '../components/ui/DataNote';
import ErrorState from '../components/ui/ErrorState';
import { useAiOperation, POLL_INTERVAL_MS } from '../hooks/useAiOperation';
import { useReportWaiting, REPORT_POLL_INTERVAL_MS } from '../hooks/useReportWaiting';
import { generatingSteps, generatingTips, generatingTitles } from '../services/mockData';
import type { ApiReportListItem, GeneratingStage } from '../types';

const ACTIVE_TASK_KEY = 'careerai:active_task';

/** 从 result_ref（如 /api/v1/reports/{id} 或 /api/v1/plans/{id}）提取资源 id */
function extractRefId(resultRef: string | null): string | null {
  if (!resultRef) return null;
  const parts = resultRef.split('/').filter(Boolean);
  return parts[parts.length - 1] ?? null;
}

export default function GeneratingPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { message } = AntApp.useApp();

  const stageParam = searchParams.get('stage');
  const stage: GeneratingStage = stageParam === '2' ? 2 : 1;
  const stepNames = useMemo(() => generatingSteps[stage], [stage]);

  // task_id：URL 优先，其次 sessionStorage（离开恢复）
  const urlTaskId = searchParams.get('task_id');
  const taskId = urlTaskId ?? sessionStorage.getItem(ACTIVE_TASK_KEY);

  // 报告等待模式（/Q3）：列表页生成中卡片点击 → /generating?reportId=xxx&stage=N（无 task_id 时）
  const reportId = searchParams.get('reportId');
  const isWaitingMode = !taskId && Boolean(reportId);

  const navigateOnSuccess = useCallback(
    (resultRef: string | null) => {
      const resourceId = extractRefId(resultRef);
      sessionStorage.removeItem(ACTIVE_TASK_KEY);
      if (stage === 2) {
        // ：Stage 2 成功 result_ref=/api/v1/plans/{plan_id} → 聚合页 planId 路径
        navigate(resourceId ? `/report/detail?planId=${resourceId}` : '/report/detail');
      } else {
        // ：Stage 1 成功 result_ref=/api/v1/reports/{report_id} → 方向选择页（用户侧链路：画像→方向→差距→计划）
        navigate(resourceId ? `/report/directions?reportId=${resourceId}` : '/report/directions');
      }
    },
    [navigate, stage],
  );

  const handleCancelled = useCallback(() => {
    sessionStorage.removeItem(ACTIVE_TASK_KEY);
    message.info('已取消生成，已填写的资料不会丢失');
    navigate('/profile');
  }, [message, navigate]);

  const { phase, steps, percent, elapsedSeconds, timeoutAlert, errorMessage, cancelLoading, cancel } = useAiOperation({
    taskId,
    stepNames,
    onSuccess: (job) => navigateOnSuccess(job.result_ref),
    onCancelled: handleCancelled,
  });

  const handleLeave = useCallback(() => {
    // 离开不取消：任务继续，结果保存到我的报告
    message.info('生成结果将保存到「我的报告」，稍后随时查看');
    navigate('/');
  }, [message, navigate]);

  const handleCancel = useCallback(() => {
    AntModal.confirm({
      title: '取消生成？',
      content: '已填写的资料不会丢失，可以稍后重新生成',
      okText: '确认取消',
      cancelText: '继续生成',
      okButtonProps: { danger: true },
      onOk: () => {
        void cancel();
      },
    });
  }, [cancel]);

  // 无任务且无 reportId（等待模式）：空态 → 重定向首页
  const showEmpty = !taskId && !reportId && phase === 'IDLE';
  useEffect(() => {
    if (showEmpty) {
      message.info('当前没有进行中的分析');
      navigate('/', { replace: true });
    }
  }, [showEmpty, message, navigate]);

  /* 生成中续接（无 task_id、有 reportId）：轮询列表等待完成（/Q3） */
  if (isWaitingMode) {
    return <ReportWaitingView reportId={reportId!} stage={stage} />;
  }

  /* 失败态 */
  if (phase === 'FAILED') {
    return (
      <div className="container-read page-body">
        <h1 className="sr-only">生成失败</h1>
        <ErrorState
          title="分析暂时失败，请稍后重试"
          description={errorMessage ?? undefined}
          onRetry={() => navigate('/profile')}
          onBack={() => navigate('/')}
        />
      </div>
    );
  }

  /* 取消态 */
  if (phase === 'CANCELLED') {
    return (
      <div className="container-read page-body">
        <h1 className="sr-only">已取消</h1>
        <ErrorState
          title="已取消生成"
          description="已填写的资料不会丢失，可以稍后重新生成"
          onRetry={() => navigate('/profile')}
          onBack={() => navigate('/')}
        />
      </div>
    );
  }

  return (
    <div className="container-read page-body">
      <GenProgress
        title={generatingTitles[stage]}
        steps={steps}
        percent={percent}
        tips={generatingTips}
        elapsedSeconds={elapsedSeconds}
        remainingSeconds={Math.max(Math.floor((180 - elapsedSeconds) / 60) * 60, 0)}
        timeoutAlert={timeoutAlert}
        onContinueWait={() => undefined}
        onCancel={handleCancel}
        onLeave={handleLeave}
      />
      {/* 轮询说明（调试可读性） */}
      <div style={{ textAlign: 'center', marginTop: 'var(--space-4)', fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>
        自动刷新间隔 {POLL_INTERVAL_MS / 1000}s{cancelLoading ? ' · 正在取消…' : ''}
      </div>
    </div>
  );
}


/* 报告等待视图（/Q3：无 task_id 的生成中续接）
   列表页生成中卡片 → 本视图；轮询 GET /reports 列表直到 completed/failed；
   completed 自动跳转报告页（stage1→画像报告 / stage2→差距计划） */
function ReportWaitingView({ reportId, stage }: { reportId: string; stage: GeneratingStage }) {
  const navigate = useNavigate();
  const { message } = AntApp.useApp();

  const handleCompleted = useCallback(
    (item: ApiReportListItem) => {
      sessionStorage.removeItem(ACTIVE_TASK_KEY);
      message.success('报告生成完成');
      // ：Stage 1 完成 → 方向选择页；Stage 2 完成 → 聚合页（既定行为，不动）
      if (stage === 2) {
        navigate(`/report/detail?reportId=${item.id}`);
      } else {
        navigate(`/report/directions?reportId=${item.id}`);
      }
    },
    [message, navigate, stage],
  );

  const handleLeave = useCallback(() => {
    // 离开不取消：任务继续，结果保存到我的报告
    message.info('生成结果将保存到「我的报告」，稍后随时查看');
    navigate('/my-reports');
  }, [message, navigate]);

  const { status, error } = useReportWaiting({ reportId, onCompleted: handleCompleted });

  /* 失败态 */
  if (status === 'failed') {
    return (
      <div className="container-read page-body">
        <h1 className="sr-only">生成失败</h1>
        <ErrorState
          title="分析暂时失败，请稍后重试"
          description={error ?? '本次报告生成失败，可重新发起分析'}
          onRetry={() => navigate('/profile')}
          onBack={() => navigate('/my-reports')}
        />
      </div>
    );
  }

  const statusText =
    status === 'running' ? 'AI 正在分析你的信息，请稍候…' : status === 'pending' ? '任务排队中，即将开始分析…' : '正在获取生成状态…';

  return (
    <div className="container-read page-body">
      <Card
        style={{ maxWidth: 640, margin: '0 auto', borderRadius: 'var(--radius-md)', textAlign: 'center' }}
        styles={{ body: { padding: 'var(--space-10)' } }}
      >
        <Spin size="large" aria-label="生成中" />
        <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 600, margin: 'var(--space-6) 0 var(--space-2)' }}>
          {generatingTitles[stage]}
        </h1>
        <div style={{ fontSize: 'var(--font-size-base)', color: 'var(--color-text-secondary)' }}>{statusText}</div>
        {error && <Alert type="warning" showIcon message={error} style={{ marginTop: 'var(--space-4)', textAlign: 'left' }} />}
        <div style={{ marginTop: 'var(--space-6)' }}>
          <DataNote>生成结果将保存到「我的报告」；可先离开，稍后随时回来查看</DataNote>
        </div>
        <div style={{ marginTop: 'var(--space-4)' }}>
          <Button type="link" onClick={handleLeave}>
            <ArrowUpOutlined /> 离开页面（不取消生成）
          </Button>
        </div>
      </Card>
      {/* 轮询说明（调试可读性） */}
      <div style={{ textAlign: 'center', marginTop: 'var(--space-4)', fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>
        自动刷新间隔 {REPORT_POLL_INTERVAL_MS / 1000}s
      </div>
    </div>
  );
}
