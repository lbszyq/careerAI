/* v1.1 计划阶段能力化展示
   阶段级 goal（目标能力）/ why（为什么）/ verify（项目验证）/ resume_value（简历资产）/ stage_completion（阶段完成条件）
   字段缺失逐项隐藏；全部缺失时不渲染（存量计划优雅降级） */
import type { ApiPlanStage } from '../../types';

interface PlanStageCapabilityProps {
  stage?: ApiPlanStage;
}

export default function PlanStageCapability({ stage }: PlanStageCapabilityProps) {
  if (!stage) return null;
  const rows = [
    { label: '目标能力', value: stage.goal },
    { label: '为什么', value: stage.why },
    { label: '项目验证', value: stage.verify },
    { label: '简历资产', value: stage.resume_value },
    { label: '阶段完成条件', value: stage.stage_completion },
  ].filter((row) => row.value && row.value.trim());
  if (rows.length === 0) return null;
  return (
    <div
      style={{
        background: 'var(--color-bg-subtle)',
        borderRadius: 'var(--radius-sm)',
        padding: 'var(--space-3) var(--space-4)',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        fontSize: 'var(--font-size-sm)',
      }}
    >
      {rows.map((row) => (
        <div key={row.label} style={{ display: 'flex', gap: 8, lineHeight: '21px' }}>
          <span style={{ color: 'var(--color-text-secondary)', flexShrink: 0, width: 88 }}>{row.label}</span>
          <span style={{ color: 'var(--color-text-primary)' }}>{row.value}</span>
        </div>
      ))}
    </div>
  );
}
