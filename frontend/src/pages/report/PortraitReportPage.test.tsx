/* ：常模占位文案诚实化（BL-017）——PortraitReportPage
   标准 1：norm=null → band 行 + DataNote 不渲染，无「当前样本量不足」「基于预置常模基准」占位文案
   标准 2（边界）：norm 非 null 且 band/note 存在时正常展示；norm=null 时报告其余部分（评分/优势/方向）不受影响 */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import PortraitReportPage from './PortraitReportPage';
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
      strengths: ['技术栈扎实', '项目经验完整'],
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

describe('PortraitReportPage 常模占位文案', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('标准 1：norm=null → band 行与 DataNote 整段隐藏，无占位文案，其余部分正常', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.includes('/reports/r1')) return envelope(makeReport(null));
      return envelope(null);
    }));

    render(
      <MemoryRouter initialEntries={['/report/portrait?reportId=r1']}>
        <PortraitReportPage />
      </MemoryRouter>,
    );

    // 评分/优势/方向等其余部分正常显示
    expect(await screen.findByText('82')).toBeInTheDocument();
    expect(screen.getByText('综合竞争力评分')).toBeInTheDocument();
    expect(screen.getByText('技术栈扎实')).toBeInTheDocument();
    expect(screen.getByText('你的优势')).toBeInTheDocument();
    expect(screen.getByText('能力五维')).toBeInTheDocument();

    // norm=null：不渲染占位文案 / band 行 / DataNote
    expect(screen.queryByText('当前样本量不足，暂不展示同届分位')).not.toBeInTheDocument();
    expect(screen.queryByText('基于预置常模基准，非真实用户池')).not.toBeInTheDocument();
    expect(screen.queryByText(/处于参考样本/)).not.toBeInTheDocument();
    // PortraitNormInfo（常模口径）也不渲染
    expect(screen.queryByText('常模口径')).not.toBeInTheDocument();
  });

  it('标准 2：norm 非 null 且 band/note 存在 → band 行与 DataNote 正常显示', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.includes('/reports/r1')) {
        return envelope(
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
      }
      return envelope(null);
    }));

    render(
      <MemoryRouter initialEntries={['/report/portrait?reportId=r1']}>
        <PortraitReportPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText('处于参考样本前 25%')).toBeInTheDocument();
    expect(screen.getByText('常模样本可能含在职人员')).toBeInTheDocument();
    // 常模口径（样本量/可靠等级）正常显示
    expect(screen.getByText('常模口径')).toBeInTheDocument();
    expect(screen.getByText('约 120 人')).toBeInTheDocument();
    expect(screen.queryByText('当前样本量不足，暂不展示同届分位')).not.toBeInTheDocument();
    expect(screen.queryByText('基于预置常模基准，非真实用户池')).not.toBeInTheDocument();
  });

  it('标准 2：norm 非 null 但 band=null（后端当前形态）→ band 行隐藏、note DataNote 正常、无占位文案', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: unknown) => {
      const u = String(url);
      if (u.includes('/reports/r1')) {
        return envelope(
          makeReport({
            matched: true,
            cohort: '2026 届本科',
            band: null,
            sample_size: 120,
            contains_employed: true,
            confidence: '中',
            note: '常模样本可能含在职人员，应届生起薪通常低于市场均值',
            disclaimer: '该指数用于能力画像参考',
          }),
        );
      }
      return envelope(null);
    }));

    render(
      <MemoryRouter initialEntries={['/report/portrait?reportId=r1']}>
        <PortraitReportPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('常模口径')).toBeInTheDocument());
    expect(screen.getByText('约 120 人')).toBeInTheDocument();
    expect(screen.getByText('常模样本可能含在职人员，应届生起薪通常低于市场均值')).toBeInTheDocument();
    expect(screen.queryByText(/处于参考样本/)).not.toBeInTheDocument();
    expect(screen.queryByText('当前样本量不足，暂不展示同届分位')).not.toBeInTheDocument();
    expect(screen.queryByText('基于预置常模基准，非真实用户池')).not.toBeInTheDocument();
  });
});
