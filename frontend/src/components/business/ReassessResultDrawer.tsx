/* 重评结果展示（/）
   Drawer 呈现四部分：①差距变化 ②计划调整预览（保留已完成标记标注）③阶段完成校验
   ④调整说明（证据引用）；底部「应用调整」/「放弃」；重复决策 3404 提示 */
import { useCallback, useEffect, useState } from 'react';
import { Alert, App as AntApp, Button, Drawer, Skeleton, Space, Tag, Typography } from 'antd';
import { CheckCircleOutlined, CloseCircleOutlined, InfoCircleOutlined, WarningOutlined } from '@ant-design/icons';
import SemanticTag from '../ui/SemanticTag';
import { feedbackApi } from '../../services/feedbackApi';
import { ApiClientError } from '../../services/http';
import { toUserMessage } from '../../services/errorMapping';
import { PHASE_NAME } from '../../utils/adapters';
import type { ApiEvidenceRef, ApiReassessmentDetail } from '../../types';

interface ReassessResultDrawerProps {
  open: boolean;
  planId: string;
  /** 重评记录 ID（latest_reassess.result_ref 末段） */
  reassessId: string | null;
  onClose: () => void;
  /** 决策成功后刷新计划（apply 携带新 progress） */
  onDecided: (progress?: number) => void;
}

const TASK_STATUS_LABEL: Record<string, string> = { todo: '未开始', doing: '进行中', done: '已完成' };
const CONFIDENCE_LABEL: Record<string, string> = { high: '高', medium: '中', low: '低' };

export default function ReassessResultDrawer({ open, planId, reassessId, onClose, onDecided }: ReassessResultDrawerProps) {
  const { message } = AntApp.useApp();
  const [detail, setDetail] = useState<ApiReassessmentDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deciding, setDeciding] = useState<'apply' | 'discard' | null>(null);

  const load = useCallback(async () => {
    if (!open || !reassessId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const data = await feedbackApi.getReassessment(planId, reassessId);
      setDetail(data);
    } catch (err) {
      setLoadError(err instanceof ApiClientError ? toUserMessage(err) : '重评结果加载失败');
    } finally {
      setLoading(false);
    }
  }, [open, reassessId, planId]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const handleDecision = async (decision: 'apply' | 'discard') => {
    if (!reassessId || deciding) return;
    setDeciding(decision);
    try {
      const result =
        decision === 'apply'
          ? await feedbackApi.applyReassessment(planId, reassessId)
          : await feedbackApi.discardReassessment(planId, reassessId);
      if (decision === 'apply') {
        message.success('已应用调整，计划已更新且保留已完成标记');
        onDecided(result.progress);
      } else {
        message.success('已放弃调整，原计划保持不变');
        onDecided();
      }
      void load(); // 刷新决策状态展示（decision=applied/discarded）
    } catch (err) {
      // 3404 重复决策：错误码映射为「该重评记录已应用或放弃，不可重复操作」
      message.error(err instanceof ApiClientError ? toUserMessage(err) : '操作失败，请稍后重试');
    } finally {
      setDeciding(null);
    }
  };

  /** ：level=已具备 的项不得再以“仍存在”危险语义展示；从“仍存在”中分离，改为“已具备（无需补齐）” */
  const remainingNeedItems = detail?.gap_change.remaining_items.filter((item) => item.level !== '已具备') ?? [];
  const alreadyHaveItems = detail?.gap_change.remaining_items.filter((item) => item.level === '已具备') ?? [];

  return (
    <Drawer
      title="重新评估结果"
      open={open}
      onClose={onClose}
      width={720}
      styles={{ body: { padding: 'var(--space-6)' } }}
    >
      {loading && !detail && <Skeleton active paragraph={{ rows: 8 }} />}
      {loadError && !detail && (
        <Alert
          type="error"
          showIcon
          message={loadError}
          action={<Button size="small" onClick={() => void load()}>重试</Button>}
        />
      )}
      {detail && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
          {/* 顶部摘要 */}
          <div style={{ padding: 'var(--space-4) var(--space-6)', borderRadius: 'var(--radius-md)', background: 'var(--color-bg-subtle)' }}>
            <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 600 }}>{detail.summary}</div>
            <div style={{ marginTop: 4, fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
              重评时间 {detail.created_at.slice(0, 16).replace('T', ' ')}
            </div>
          </div>

          {/* ① 差距变化 */}
          <Section title="① 差距变化" icon={<InfoCircleOutlined />}>
            <Typography.Paragraph style={{ margin: '0 0 var(--space-3)', fontSize: 'var(--font-size-sm)' }}>
              {detail.gap_change.summary}
            </Typography.Paragraph>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              {detail.gap_change.resolved_items.map((item) => (
                <div key={`resolved-${item.skill}`} style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'flex-start' }}>
                  <SemanticTag semantic="success" icon={<CheckCircleOutlined />}>已补齐</SemanticTag>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 'var(--font-size-base)' }}>{item.skill}</div>
                    <EvidenceList refs={item.evidence_refs} />
                  </div>
                </div>
              ))}
              {remainingNeedItems.map((item) => (
                <div key={`remaining-${item.skill}`} style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'flex-start' }}>
                  <SemanticTag semantic="danger" icon={<CloseCircleOutlined />}>仍存在</SemanticTag>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 'var(--font-size-base)' }}>
                      {item.skill}
                      {item.level && <span style={{ color: 'var(--color-text-secondary)' }}>（{item.level}）</span>}
                      {item.confidence && <Tag style={{ marginLeft: 8 }}>置信度 {CONFIDENCE_LABEL[item.confidence]}</Tag>}
                    </div>
                    <EvidenceList refs={item.evidence_refs} />
                  </div>
                </div>
              ))}
              {alreadyHaveItems.map((item) => (
                <div key={`already-have-${item.skill}`} style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'flex-start' }}>
                  <SemanticTag semantic="success" icon={<CheckCircleOutlined />}>已具备（无需补齐）</SemanticTag>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 'var(--font-size-base)' }}>
                      {item.skill}
                      {item.level && <span style={{ color: 'var(--color-text-secondary)' }}>（{item.level}）</span>}
                      {item.confidence && <Tag style={{ marginLeft: 8 }}>置信度 {CONFIDENCE_LABEL[item.confidence]}</Tag>}
                    </div>
                    <EvidenceList refs={item.evidence_refs} />
                  </div>
                </div>
              ))}
            </div>
          </Section>

          {/* ② 计划调整预览 */}
          <Section title="② 计划调整预览" icon={<InfoCircleOutlined />}>
            <Typography.Paragraph style={{ margin: '0 0 var(--space-3)', fontSize: 'var(--font-size-sm)' }}>
              {detail.plan_adjustment.summary}
            </Typography.Paragraph>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              {detail.plan_adjustment.changes.map((change, idx) => (
                <div key={`change-${idx}`} style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'flex-start' }}>
                  <ChangeTag action={change.action} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 'var(--font-size-base)' }}>
                      {change.target === 'task' ? `任务「${change.name ?? '未命名任务'}」` : `阶段「${PHASE_NAME[change.stage]}」`}
                      <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>（{PHASE_NAME[change.stage]}）</span>
                    </div>
                    <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>原因：{change.reason}</div>
                    <EvidenceList refs={change.evidence_refs} />
                  </div>
                </div>
              ))}
            </div>
            {detail.plan_adjustment.conflicts.length > 0 && (
              <Alert
                type="warning"
                showIcon
                icon={<WarningOutlined />}
                style={{ marginTop: 'var(--space-3)' }}
                message="已完成标记冲突"
                description={detail.plan_adjustment.conflicts.map((c) => `「${c.task_name}」${c.note}`).join('；')}
              />
            )}
            <div style={{ marginTop: 'var(--space-3)', fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>
              已完成的标记将保留，不会被调整回退
            </div>
          </Section>

          {/* ③ 阶段完成校验 */}
          <Section title="③ 阶段完成校验" icon={<InfoCircleOutlined />}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
              {(Object.keys(detail.stage_checks) as Array<'short' | 'mid' | 'long'>).map((key) => {
                const check = detail.stage_checks[key];
                return (
                  <div key={key} style={{ padding: 'var(--space-3) var(--space-4)', borderRadius: 'var(--radius-sm)', border: '1px solid var(--color-border-default)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 'var(--font-size-base)', fontWeight: 500 }}>{PHASE_NAME[key]}</span>
                      <SemanticTag semantic={check.result === 'pass' ? 'success' : 'danger'}>
                        {check.result === 'pass' ? '通过' : '未通过'}
                      </SemanticTag>
                      {check.stay && <Tag style={{ borderRadius: 'var(--radius-pill)', color: 'var(--color-warning-600)', background: 'var(--color-warning-100)', borderColor: 'transparent' }}>停留当前阶段</Tag>}
                    </div>
                    <div style={{ marginTop: 6, fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>{check.reason}</div>
                    {check.suggestion && (
                      <div style={{ marginTop: 4, fontSize: 'var(--font-size-sm)', color: 'var(--color-info-600)' }}>补齐建议：{check.suggestion}</div>
                    )}
                  </div>
                );
              })}
            </div>
          </Section>

          {/* ④ 调整说明 */}
          <Section title="④ 调整说明" icon={<InfoCircleOutlined />}>
            <Typography.Paragraph style={{ margin: '0 0 var(--space-3)', fontSize: 'var(--font-size-sm)' }}>
              {detail.adjustment_explanation.summary}
            </Typography.Paragraph>
            <EvidenceList refs={detail.adjustment_explanation.evidence_refs} />
          </Section>

          {/* 底部决策操作 */}
          <div style={{ position: 'sticky', bottom: 0, background: 'var(--color-bg-surface)', padding: 'var(--space-4) 0', borderTop: '1px solid var(--color-divider)' }}>
            {detail.decision === 'undecided' ? (
              <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
                <Button onClick={() => void handleDecision('discard')} loading={deciding === 'discard'}>
                  放弃
                </Button>
                <Button type="primary" loading={deciding === 'apply'} onClick={() => void handleDecision('apply')}>
                  应用调整
                </Button>
              </Space>
            ) : (
              <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)', textAlign: 'right' }}>
                {detail.decision === 'applied' ? '已应用调整，计划已更新（保留已完成标记）' : '已放弃调整，原计划保持不变'}
                {detail.decided_at && ` · ${detail.decided_at.slice(0, 16).replace('T', ' ')}`}
              </div>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}

/* 分节卡片（tokens 对齐设计系统：surface 底 + border + radius-md） */
function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{ padding: 'var(--space-4)', borderRadius: 'var(--radius-md)', background: 'var(--color-bg-surface)', border: '1px solid var(--color-border-default)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-3)', fontSize: 'var(--font-size-lg)', fontWeight: 600, color: 'var(--color-text-primary)' }}>
        {icon}
        {title}
      </div>
      {children}
    </div>
  );
}

/* 调整动作标签：add=新增（success）/ modify=修改（info）/ remove=移除（danger） */
function ChangeTag({ action }: { action: 'add' | 'modify' | 'remove' }) {
  const map = {
    add: { semantic: 'success' as const, label: '新增' },
    modify: { semantic: 'info' as const, label: '修改' },
    remove: { semantic: 'danger' as const, label: '移除' },
  };
  return <SemanticTag semantic={map[action].semantic}>{map[action].label}</SemanticTag>;
}

/* 证据引用列表：achievement 含链接（rel=noopener noreferrer 新窗口）；task 含状态证据 */
function EvidenceList({ refs }: { refs: ApiEvidenceRef[] }) {
  if (!refs || refs.length === 0) return null;
  return (
    <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 2 }}>
      {refs.map((ref) => (
        <div key={`${ref.type}-${ref.id}`} style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>
          {ref.type === 'achievement' ? (
            <>
              证据·成果：
              {ref.url ? (
                <a href={ref.url} target="_blank" rel="noopener noreferrer">
                  {ref.name}
                </a>
              ) : (
                ref.name
              )}
            </>
          ) : (
            <>证据·任务：{ref.name}（{TASK_STATUS_LABEL[ref.status ?? ''] ?? ref.status ?? '未知状态'}）</>
          )}
        </div>
      ))}
    </div>
  );
}
