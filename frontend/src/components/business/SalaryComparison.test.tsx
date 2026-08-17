/* ：方向卡片薪资对比组件 SalaryComparison（BL-026 方案②）
   标准 1：4 个 level 徽标文案映射全测 + note 渲染
   标准 3：null → 整块隐藏（无空占位）；no_data → 只渲染 note 无徽标
   标准 4：字段缺失（undefined）→ 隐藏不崩溃；未知 level 防御兜底不渲染 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import SalaryComparison from './SalaryComparison';
import type { SalaryComparison as SalaryComparisonData } from '../../types';

const LEVEL_CASES: { level: string; label: string }[] = [
  { level: 'below_p25', label: '低于市场 25 分位' },
  { level: 'p25_p50', label: '市场 25-50 分位' },
  { level: 'p50_p75', label: '市场 50-75 分位' },
  { level: 'above_p75', label: '高于市场 75 分位' },
];

describe('SalaryComparison 方向卡片薪资对比', () => {
  it.each(LEVEL_CASES)('level=$level → 渲染徽标「$label」+ note 文本', ({ level, label }) => {
    const comparison: SalaryComparisonData = {
      level: level as SalaryComparisonData['level'],
      note: `note-${level}`,
    };
    render(<SalaryComparison comparison={comparison} />);

    expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText(`note-${level}`)).toBeInTheDocument();
  });

  it('标准 3：comparison=null → 整块隐藏（容器为空，无空占位）', () => {
    const { container } = render(<SalaryComparison comparison={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('标准 4：comparison 缺省（undefined，旧接口）→ 隐藏不崩溃', () => {
    const { container } = render(<SalaryComparison />);
    expect(container).toBeEmptyDOMElement();
  });

  it('标准 3：level=no_data → 只渲染 note「暂无该岗位薪资数据」，无徽标', () => {
    render(<SalaryComparison comparison={{ level: 'no_data', note: '暂无该岗位薪资数据' }} />);

    expect(screen.getByText('暂无该岗位薪资数据')).toBeInTheDocument();
    LEVEL_CASES.forEach(({ label }) => {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    });
  });

  it('防御：未知 level → 不渲染（不崩溃）', () => {
    const comparison = { level: 'weird_level', note: 'x' } as unknown as SalaryComparisonData;
    const { container } = render(<SalaryComparison comparison={comparison} />);
    expect(container).toBeEmptyDOMElement();
  });
});
