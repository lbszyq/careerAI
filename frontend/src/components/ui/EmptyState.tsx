/* C-14 空状态 EmptyState：组件库 Empty + 自定义文案 + 操作按钮 */
import { Empty, Button } from 'antd';
import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  description?: string;
  actionText?: string;
  onAction?: () => void;
}

export default function EmptyState({ title, description, actionText, onAction }: EmptyStateProps) {
  return (
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        <div style={{ maxWidth: 320, margin: '0 auto' }}>
          <div style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600, color: 'var(--color-text-primary)' }}>{title}</div>
          {description && (
            <div style={{ marginTop: 4, fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>{description}</div>
          )}
        </div>
      }
      style={{ padding: 'var(--space-12) 0' }}
    >
      {actionText && onAction && (
        <Button type="primary" onClick={onAction}>
          {actionText}
        </Button>
      )}
    </Empty>
  );
}

export type { ReactNode };
