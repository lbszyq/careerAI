/* v1.1 置信度原因拆解 ConfidenceReasons
   supporting=主要依据（+，success 绿）/ concerns=降低因素（-，warning 橙）
   挂载画像常模 / 方向推荐 / 差距分析；两列表均缺失/为空时不渲染（优雅降级） */
import { PlusCircleOutlined, MinusCircleOutlined } from '@ant-design/icons';
import type { ConfidenceReasons as ConfidenceReasonsData } from '../../types';

interface ConfidenceReasonsProps {
  reasons?: ConfidenceReasonsData | null;
  title?: string;
}

export default function ConfidenceReasons({ reasons, title = '置信度说明' }: ConfidenceReasonsProps) {
  const supporting = Array.isArray(reasons?.supporting) ? reasons.supporting : [];
  const concerns = Array.isArray(reasons?.concerns) ? reasons.concerns : [];
  if (supporting.length === 0 && concerns.length === 0) return null;
  return (
    <div
      style={{
        background: 'var(--color-bg-subtle)',
        borderRadius: 'var(--radius-sm)',
        padding: 'var(--space-3) var(--space-4)',
        fontSize: 'var(--font-size-sm)',
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6 }}>{title}</div>
      {supporting.length > 0 && (
        <>
          <div style={{ color: 'var(--color-success-600)', fontWeight: 500, marginBottom: 4 }}>主要依据（+）</div>
          {supporting.map((text, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, lineHeight: '20px', marginBottom: 4 }}>
              <PlusCircleOutlined style={{ color: 'var(--color-success-600)', marginTop: 3, flexShrink: 0 }} />
              <span>{text}</span>
            </div>
          ))}
        </>
      )}
      {concerns.length > 0 && (
        <>
          <div style={{ color: 'var(--color-warning-600)', fontWeight: 500, marginBottom: 4, marginTop: supporting.length > 0 ? 6 : 0 }}>
            降低因素（-）
          </div>
          {concerns.map((text, i) => (
            <div key={i} style={{ display: 'flex', gap: 6, lineHeight: '20px', marginBottom: 4 }}>
              <MinusCircleOutlined style={{ color: 'var(--color-warning-600)', marginTop: 3, flexShrink: 0 }} />
              <span>{text}</span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
