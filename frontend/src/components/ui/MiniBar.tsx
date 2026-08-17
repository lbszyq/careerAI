/* C-19 匹配度细条 MiniBar：无背景轨道，细条 + 数值 */
interface MiniBarProps {
  value: number;
  showValue?: boolean;
}

function barColor(value: number): string {
  if (value >= 70) return 'var(--color-success-600)';
  if (value >= 40) return 'var(--color-warning-600)';
  return 'var(--color-danger-600)';
}

export default function MiniBar({ value, showValue = true }: MiniBarProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', width: '100%' }}>
      <div
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="匹配度"
        style={{
          flex: 1,
          height: 6,
          borderRadius: 'var(--radius-pill)',
          border: '1px solid var(--color-border-strong)',
          background: 'transparent',
          overflow: 'hidden',
        }}
      >
        <div style={{ width: `${value}%`, height: '100%', borderRadius: 'var(--radius-pill)', backgroundColor: barColor(value) }} />
      </div>
      {showValue && (
        <span className="tnum" style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, color: barColor(value) }}>
          {value}%
        </span>
      )}
    </div>
  );
}
