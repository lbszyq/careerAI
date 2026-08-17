/* SalaryComparison：方向卡片「期望薪资 vs 岗位薪资分位」对比行（/ BL-026 方案②）
   纯渲染：只透传 note / level，不参与原始薪资数字（期望薪资/分位值）的重算或比较，也不重复渲染
   诚实隐藏：null / undefined → 整块隐藏（无空占位、无高度残留）；no_data → 只渲染 note 无徽标 */
import SemanticTag from '../ui/SemanticTag';
import type { SalaryComparison as SalaryComparisonData, SalaryLevel } from '../../types';

interface SalaryComparisonProps {
  comparison?: SalaryComparisonData | null;
}

/** level → 徽标文案（no_data 不渲染徽标，故排除） */
const LEVEL_LABEL: Record<Exclude<SalaryLevel, 'no_data'>, string> = {
  below_p25: '低于市场 25 分位',
  p25_p50: '市场 25-50 分位',
  p50_p75: '市场 50-75 分位',
  above_p75: '高于市场 75 分位',
};

/** no_data 兜底文案（与后端契约 note 一致） */
const NO_DATA_NOTE = '暂无该岗位薪资数据';

export default function SalaryComparison({ comparison }: SalaryComparisonProps) {
  // 诚实隐藏：null / undefined（旧接口字段缺失）→ 不渲染任何内容
  if (!comparison) return null;

  const { level, note } = comparison;

  if (level === 'no_data') {
    return (
      <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>
        {note || NO_DATA_NOTE}
      </div>
    );
  }

  // 防御兜底：未知 level 不渲染（不崩溃）
  const label = LEVEL_LABEL[level];
  if (!label) return null;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
      <SemanticTag semantic="info">{label}</SemanticTag>
      {note && <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>{note}</span>}
    </div>
  );
}
