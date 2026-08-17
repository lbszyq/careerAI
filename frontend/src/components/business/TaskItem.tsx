/* C-30 任务项 TaskItem
   结构：左 Checkbox + 中 任务名称 + 阶段 Tag + 预估耗时 + 右 状态 Tag
   状态：未完成 / 进行中（warning 边框）/ 已完成（次级色 + 删除线）
    决策③：报告流查看态不可勾选（readOnly）；我的计划执行态可勾选 */
import { Checkbox, Tag } from 'antd';
import SemanticTag from '../ui/SemanticTag';
import type { PlanTask } from '../../types';

interface TaskItemProps {
  task: PlanTask;
  phaseName?: string;
  readOnly?: boolean;
  onToggle?: (id: string, checked: boolean) => void;
}

const statusLabel = { pending: '未开始', doing: '进行中', done: '已完成' } as const;

export default function TaskItem({ task, phaseName, readOnly, onToggle }: TaskItemProps) {
  const done = task.status === 'done';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 'var(--space-3)',
        padding: 'var(--space-3) var(--space-4)',
        borderRadius: 'var(--radius-sm)',
        background: 'var(--color-bg-surface)',
        border: `1px solid ${task.status === 'doing' ? 'var(--color-warning-600)' : 'var(--color-border-default)'}`,
      }}
    >
      <Checkbox
        checked={done}
        disabled={false}
        onChange={(e) => {
          // ：查看态清晰勾选框（可点击视觉），决策③ 查看态不可勾选 → 无操作
          if (readOnly) return;
          onToggle?.(task.id, e.target.checked);
        }}
        aria-label={`${task.name}${done ? '（已完成）' : '（未完成）'}`}
        style={{ marginRight: 0 }}
      />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 'var(--font-size-base)',
            color: done ? 'var(--color-text-secondary)' : 'var(--color-text-primary)',
            textDecoration: done ? 'line-through' : 'none',
          }}
        >
          {task.name}
        </div>
        <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 2, flexWrap: 'wrap' }}>
          {phaseName && <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>{phaseName}</span>}
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>{task.duration}</span>
          <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>推荐资源：{task.resource}</span>
        </div>
        {task.acceptanceCriteria && (
          <div style={{ marginTop: 4, fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>
            验证标准：{task.acceptanceCriteria}
          </div>
        )}
      </div>
      {task.coveredByAchievement && <SemanticTag semantic="success">已由成果覆盖</SemanticTag>}

      <Tag
        style={{
          borderRadius: 'var(--radius-pill)',
          color: done ? 'var(--color-text-secondary)' : task.status === 'doing' ? 'var(--color-warning-600)' : 'var(--color-text-tertiary)',
          background: done ? 'var(--color-bg-subtle)' : task.status === 'doing' ? 'var(--color-warning-100)' : 'transparent',
          borderColor: 'transparent',
          margin: 0,
        }}
      >
        {statusLabel[task.status]}
      </Tag>
    </div>
  );
}
