/* ：常模占位文案诚实化（BL-017）——ReportDetailPage（spot 6）
   标准 1：norm=null → 画像摘要不渲染占位文案（页面不传「当前样本量不足」「基于预置常模基准」）
   标准 2：norm 非 null 且 band/note 存在 → 正常传参渲染 */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider, App as AntApp } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ReportDetailPage from './ReportDetailPage';
import { mockSalaryComparisonDirections } from '../../services/mockData';
import type { ApiPortraitNorm, ApiReportDetail } from '../../types';

// 雷达图依赖 echarts canvas，jsdom 无 canvas → mock
vi.mock('../../components/business/RadarChart', () => ({
  default: () => <div data-testid="mock-radar" />,
}));

function makeReport(norm: ApiPortraitNorm | null): ApiReportDetail {
  return {
    id: 'r1',
    stage: 'stage2',
    status: 'completed',
    portrait: {
      overall_score: 82,
      dimensions: { technical: 80, project: 70 },
      norm,
      strengths: ['技术栈扎实'],
      weaknesses: ['行业认知待提升'],
      confidence: '高',
    },
    directions: [],
    gap_analysis: null,
    plan: null,
    created_at: '2026-08-15T10:00:00',
    finished_at: '2026-08-15T10:05:00',
  };
}

const envelope = (data: unknown) => ({
  status: 200,
  json: async () => ({ code: 0, message: 'ok', data }),
});

function renderDetail(report: ApiReportDetail) {
  vi.stubGlobal('fetch', vi.fn(async (url: unknown) => {
    const u = String(url);
    if (u.includes('/reports/r1')) return envelope(report);
    return envelope(null);
  }));
  return render(
    <ConfigProvider>
      <AntApp>
        <MemoryRouter initialEntries={['/report/detail?reportId=r1']}>
          <ReportDetailPage />
        </MemoryRouter>
      </AntApp>
    </ConfigProvider>,
  );
}

describe('ReportDetailPage 常模占位文案传参', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('标准 1：norm=null → 画像摘要不渲染占位文案', async () => {
    renderDetail(makeReport(null));

    expect(await screen.findByText('82')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '职业画像' })).toBeInTheDocument();
    expect(screen.queryByText('当前样本量不足，暂不展示同届分位')).not.toBeInTheDocument();
    expect(screen.queryByText('基于预置常模基准，非真实用户池')).not.toBeInTheDocument();
    expect(screen.queryByText(/处于参考样本/)).not.toBeInTheDocument();
  });

  it('标准 2：norm 非 null 且 band/note 存在 → 正常传参渲染', async () => {
    renderDetail(
      makeReport({
        matched: true,
        cohort: '2026 届本科',
        band: '前 25%',
        sample_size: 120,
        contains_employed: false,
        confidence: '中',
        note: '常模样本可能含在职人员',
        disclaimer: '该指数用于能力画像参考',
      }),
    );

    expect(await screen.findByText('处于参考样本前 25%')).toBeInTheDocument();
    expect(screen.getByText('常模样本可能含在职人员')).toBeInTheDocument();
  });

  it('标准 2：方向推荐区展示薪资对比行（复用 SalaryComparison）', async () => {
    const direction = mockSalaryComparisonDirections.find((d) => d.id === 'mock-salary-p50-p75');
    if (!direction) throw new Error('mock direction 不存在');
    renderDetail({
      ...makeReport(null),
      portrait: null,
      directions: [direction],
    });

    expect(await screen.findByText('市场 50-75 分位')).toBeInTheDocument();
    expect(screen.getByText(/50-75 分位段/)).toBeInTheDocument();
  });

  it('标准 2：norm 非 null 但 band=null → 不传占位文案（其余展示不受影响）', async () => {
    renderDetail(
      makeReport({
        matched: true,
        cohort: '2026 届本科',
        band: null,
        sample_size: 120,
        contains_employed: false,
        confidence: '中',
        note: null,
        disclaimer: '该指数用于能力画像参考',
      }),
    );

    await waitFor(() => expect(screen.getByText('82')).toBeInTheDocument());
    expect(screen.queryByText('当前样本量不足，暂不展示同届分位')).not.toBeInTheDocument();
    expect(screen.queryByText('基于预置常模基准，非真实用户池')).not.toBeInTheDocument();
    expect(screen.queryByText(/处于参考样本/)).not.toBeInTheDocument();
    // 报告其余部分正常
    expect(screen.getByText('技术栈扎实')).toBeInTheDocument();
  });
});
