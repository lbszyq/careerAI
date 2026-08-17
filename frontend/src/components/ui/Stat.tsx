/* C-17 统计数字 Stat：大数字 + 标签；≥24px 用 accent-500 金色，<24px 用 accent-600 */
interface StatProps {
  value: string | number;
  label: string;
  size?: 'lg' | 'xl';
  color?: 'default' | 'accent';
}

export default function Stat({ value, label, size = 'lg', color = 'default' }: StatProps) {
  const isLarge = size === 'xl';
  const textColor =
    color === 'accent' ? (isLarge ? 'var(--color-accent-500)' : 'var(--color-accent-600)') : 'var(--color-text-primary)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
      <span
        className="tnum"
        style={{
          fontSize: isLarge ? 'var(--font-size-3xl)' : 'var(--font-size-2xl)',
          fontWeight: 700,
          lineHeight: 1.2,
          color: textColor,
        }}
      >
        {value}
      </span>
      <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>{label}</span>
    </div>
  );
}
