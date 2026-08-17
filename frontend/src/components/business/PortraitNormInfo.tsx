/* v1.1 画像卡常模口径信息
   口径显性化：参考样本（年份×城市等级×专业大类）/ 样本量 / 是否含在职 / 可靠等级
   + 置信度原因拆解（ConfidenceReasons）+ 免责说明；字段缺失逐项隐藏（优雅降级） */
import DataNote from '../ui/DataNote';
import ConfidenceReasons from './ConfidenceReasons';
import type { ApiPortraitNorm } from '../../types';

interface PortraitNormInfoProps {
  norm?: ApiPortraitNorm | null;
}

export default function PortraitNormInfo({ norm }: PortraitNormInfoProps) {
  if (!norm) return null;
  const rows: { label: string; value: string }[] = [];
  if (norm.cohort) rows.push({ label: '参考样本', value: norm.cohort });
  if (typeof norm.sample_size === 'number' && norm.sample_size > 0) {
    rows.push({ label: '样本量', value: `约 ${norm.sample_size} 人` });
  }
  if (typeof norm.contains_employed === 'boolean') {
    rows.push({ label: '含在职样本', value: norm.contains_employed ? '是' : '否' });
  }
  if (norm.confidence) rows.push({ label: '可靠等级', value: norm.confidence });
  const supporting = Array.isArray(norm.confidence_reasons?.supporting) ? norm.confidence_reasons.supporting : [];
  const concerns = Array.isArray(norm.confidence_reasons?.concerns) ? norm.confidence_reasons.concerns : [];
  const hasReasons = supporting.length > 0 || concerns.length > 0;
  if (rows.length === 0 && !hasReasons && !norm.disclaimer) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginTop: 'var(--space-3)' }}>
      {rows.length > 0 && (
        <div style={{ background: 'var(--color-bg-subtle)', borderRadius: 'var(--radius-sm)', padding: 'var(--space-3) var(--space-4)' }}>
          <div style={{ fontSize: 'var(--font-size-xs)', fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: 6 }}>常模口径</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 'var(--font-size-sm)' }}>
            {rows.map((row) => (
              <div key={row.label} style={{ display: 'flex', gap: 8, lineHeight: '20px' }}>
                <span style={{ color: 'var(--color-text-secondary)', flexShrink: 0, width: 72 }}>{row.label}</span>
                <span>{row.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <ConfidenceReasons reasons={norm.confidence_reasons} title="常模置信度说明" />
      {norm.disclaimer && <DataNote>{norm.disclaimer}</DataNote>}
    </div>
  );
}
