/* ：常模占位文案诚实化（BL-017）——PortraitSummaryCard
   标准 1：norm=null（不传 percentileText/scoreNote/norm）→ 不渲染「当前样本量不足」「基于预置常模基准」占位文案
   标准 2（边界）：percentileText/scoreNote 传入时正常渲染；norm 非 null 时 PortraitNormInfo 正常显示样本量/可靠等级 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import PortraitSummaryCard from './PortraitSummaryCard';

// 雷达图依赖 echarts canvas，jsdom 无 canvas → mock 为空占位
vi.mock('./RadarChart', () => ({
  default: () => <div data-testid="mock-radar" />,
}));

const radar = { dimensions: [{ name: '技术能力', score: 80 }] };

describe('PortraitSummaryCard 常模占位文案', () => {
  it('标准 1：norm=null 不传 percentileText/scoreNote → 不渲染任何占位文案', () => {
    render(<PortraitSummaryCard score={82} radar={radar} date="2026-08-15" />);

    expect(screen.getByText('综合竞争力评分')).toBeInTheDocument();
    expect(screen.getByText('82')).toBeInTheDocument();
    expect(screen.getByTestId('mock-radar')).toBeInTheDocument();
    expect(screen.queryByText('当前样本量不足，暂不展示同届分位')).not.toBeInTheDocument();
    expect(screen.queryByText('基于预置常模基准，非真实用户池')).not.toBeInTheDocument();
    expect(screen.queryByText(/处于参考样本/)).not.toBeInTheDocument();
  });

  it('标准 2：percentileText/scoreNote 传入时正常渲染（norm 非 null 展示不变）', () => {
    render(
      <PortraitSummaryCard
        score={82}
        radar={radar}
        percentileText="处于参考样本前 25%"
        scoreNote="常模样本可能含在职人员"
      />,
    );

    expect(screen.getByText('处于参考样本前 25%')).toBeInTheDocument();
    expect(screen.getByText('常模样本可能含在职人员')).toBeInTheDocument();
  });

  it('标准 2：norm 非 null 时 PortraitNormInfo 正常显示样本量/可靠等级，band=null 不渲染占位', () => {
    render(
      <PortraitSummaryCard
        score={82}
        radar={radar}
        norm={{
          matched: true,
          cohort: '2026 届本科',
          band: null,
          sample_size: 120,
          contains_employed: false,
          confidence: '中',
          note: null,
          disclaimer: '该指数用于能力画像参考，不代表实际就业概率',
        }}
      />,
    );

    expect(screen.getByText('常模口径')).toBeInTheDocument();
    expect(screen.getByText('约 120 人')).toBeInTheDocument();
    expect(screen.getByText('可靠等级')).toBeInTheDocument();
    expect(screen.getByText('中')).toBeInTheDocument();
    expect(screen.queryByText('当前样本量不足，暂不展示同届分位')).not.toBeInTheDocument();
    expect(screen.queryByText('基于预置常模基准，非真实用户池')).not.toBeInTheDocument();
  });
});
