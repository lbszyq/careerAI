/* C-22 数据说明 DataNote：口径 / 样本量等弱化说明 */
import { InfoCircleOutlined } from '@ant-design/icons';

interface DataNoteProps {
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export default function DataNote({ children, style }: DataNoteProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 'var(--space-1)',
        fontSize: 'var(--font-size-xs)',
        color: 'var(--color-text-secondary)',
        ...style,
      }}
    >
      <InfoCircleOutlined style={{ marginTop: 4, color: 'var(--color-text-tertiary)' }} />
      <span>{children}</span>
    </div>
  );
}
