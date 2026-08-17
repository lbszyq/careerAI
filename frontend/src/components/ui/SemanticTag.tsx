/* C-20 语义标签 Tag：success/warning/danger/info 语义映射
   ：trendSemantic/heatSemantic/TagSemantic 已拆至 utils/semanticTags.ts（react-refresh 混合导出清理） */
import { Tag } from 'antd';
import type { TagSemantic } from '../../utils/semanticTags';

const semanticMap: Record<TagSemantic, { color: string; bg: string }> = {
  success: { color: 'var(--color-success-600)', bg: 'var(--color-success-100)' },
  warning: { color: 'var(--color-warning-600)', bg: 'var(--color-warning-100)' },
  danger: { color: 'var(--color-danger-600)', bg: 'var(--color-danger-100)' },
  info: { color: 'var(--color-info-600)', bg: 'var(--color-info-100)' },
};

interface SemanticTagProps {
  semantic: TagSemantic;
  children: React.ReactNode;
  icon?: React.ReactNode;
}

export default function SemanticTag({ semantic, children, icon }: SemanticTagProps) {
  const { color, bg } = semanticMap[semantic];
  return (
    <Tag
      icon={icon}
      style={{
        color,
        background: bg,
        borderColor: 'transparent',
        borderRadius: 'var(--radius-pill)',
        height: 24,
        lineHeight: '22px',
        padding: '0 10px',
        fontSize: 'var(--font-size-xs)',
        fontWeight: 500,
      }}
    >
      {children}
    </Tag>
  );
}
