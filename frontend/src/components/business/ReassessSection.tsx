/* 申请重新评估入口（/）
   - 前置判定：reassess_eligible=false 置灰 + 展示 reason（默认「请先上传成果或标记任务进度」）
   - 点击 → 确认弹窗（说明依据成果与任务状态评估，画像/方向不变）→ POST → 进行中（可离开页面）
   - 失败 → 降级提示 + 「重试」（重试 = 再次 POST），原计划不变
   - 成功 → 结果入口（latest_reassess.result_ref）→ onViewResult */
import { App as AntApp, Alert, Button, Spin } from 'antd';
import { RedoOutlined } from '@ant-design/icons';
import { REASSESS_POLL_INTERVAL_MS, useReassessFlow, type ReassessPhase } from '../../hooks/useReassessFlow';
import type { ApiLatestReassess } from '../../types';

const DEFAULT_REASON = '请先上传成果或标记任务进度';

interface ReassessSectionProps {
  planId: string;
  /** 前置：成果数 ≥1 或存在非 todo 任务；存量计划无字段视为 false（置灰） */
  eligible: boolean;
  reason: string | null;
  latestReassess: ApiLatestReassess | null;
  /** 计划数据变更后刷新（父级） */
  onPlanChanged: () => void;
  /** 打开重评结果 Drawer */
  onViewResult: () => void;
}

export default function ReassessSection({ planId, eligible, reason, latestReassess, onPlanChanged, onViewResult }: ReassessSectionProps) {
  const { message, modal } = AntApp.useApp();

  const { phase, requesting, errorMessage, request, retry } = useReassessFlow({
    planId,
    latestReassess,
    onPlanChanged,
    showError: (msg) => message.error(msg),
  });

  const handleClick = () => {
    modal.confirm({
      title: '申请重新评估？',
      content: '将依据你上传的成果与任务完成状态重新评估差距与成长计划；职业画像与方向推荐保持不变',
      okText: '申请',
      cancelText: '取消',
      onOk: () => request(),
    });
  };

  const showResultEntry = Boolean(latestReassess?.status === 'succeeded' && latestReassess.result_ref);

  return (
    <div
      style={{
        marginTop: 'var(--space-6)',
        padding: 'var(--space-4) var(--space-6)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--color-bg-surface)',
        border: '1px solid var(--color-border-default)',
      }}
    >
      <ReassessContent
        phase={phase}
        eligible={eligible}
        reason={reason}
        requesting={requesting}
        errorMessage={errorMessage}
        showResultEntry={showResultEntry}
        onRequest={handleClick}
        onRetry={retry}
        onViewResult={onViewResult}
      />
      <div style={{ marginTop: 'var(--space-3)', fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>
        重评预计 1-3 分钟，进行中可离开页面；完成后结果将出现在这里（轮询间隔 {REASSESS_POLL_INTERVAL_MS / 1000}s）
      </div>
    </div>
  );
}

interface ReassessContentProps {
  phase: ReassessPhase;
  eligible: boolean;
  reason: string | null;
  requesting: boolean;
  errorMessage: string | null;
  showResultEntry: boolean;
  onRequest: () => void;
  onRetry: () => void;
  onViewResult: () => void;
}

function ReassessContent({ phase, eligible, reason, requesting, errorMessage, showResultEntry, onRequest, onRetry, onViewResult }: ReassessContentProps) {
  /* 进行中：加载态（可离开页面，返回后由 latest_reassess 恢复） */
  if (phase === 'inProgress') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)' }}>
        <Spin size="small" aria-label="重评进行中" />
        <div>
          <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 500 }}>正在根据你的成果重新评估…</div>
          <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
            预计 1-3 分钟，可先离开页面，完成后结果将出现在这里
          </div>
        </div>
      </div>
    );
  }

  /* 失败：降级提示 + 重试（原计划不变） */
  if (phase === 'failed') {
    return (
      <div>
        <Alert
          type="error"
          showIcon
          message={errorMessage || '重新评估失败，请稍后重试'}
          description="原计划保持不变，不会产生半成品调整"
          action={
            <Button size="small" danger loading={requesting} icon={<RedoOutlined />} onClick={() => void onRetry()}>
              重试
            </Button>
          }
        />
      </div>
    );
  }

  /* 空闲：结果入口（如有）+ 申请按钮常驻（前置满足即可再次申请） */
  const disabled = !eligible;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      {showResultEntry && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--space-4)', padding: 'var(--space-3) var(--space-4)', borderRadius: 'var(--radius-sm)', background: 'var(--color-bg-subtle)' }}>
          <div>
            <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 500 }}>最近一次重新评估已完成</div>
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>查看差距变化、计划调整预览与阶段完成校验结果</div>
          </div>
          <Button type="primary" onClick={onViewResult}>
            查看重评结果
          </Button>
        </div>
      )}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--space-4)' }}>
        <div>
          <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 500 }}>申请重新评估</div>
          <div style={{ fontSize: 'var(--font-size-sm)', color: disabled ? 'var(--color-text-tertiary)' : 'var(--color-text-secondary)' }}>
            {disabled ? (reason || DEFAULT_REASON) : '基于成果与任务状态，重新评估差距与成长计划'}
          </div>
        </div>
        <Button type="primary" disabled={disabled} loading={requesting} onClick={onRequest}>
          申请重新评估
        </Button>
      </div>
    </div>
  );
}
