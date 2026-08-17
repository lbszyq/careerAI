/* ：常模占位文案诚实化（BL-017）——HomePage（spot 5）
   标准 1：norm=null → HomePage 不向 PortraitSummaryCard 传占位文案（页面不渲染「当前样本量不足」「基于预置常模基准」）
   标准 2：norm 非 null 且 band/note 存在 → 正常传参渲染 */
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import HomePage from './HomePage';
import { AuthContext } from '../stores/useAuthStore';
import type { ApiPortraitNorm, ApiReportDetail, ApiUser } from '../types';

// 雷达图依赖 echarts canvas，jsdom 无 canvas → mock
vi.mock('../components/business/RadarChart', () => ({
  default: () => <div data-testid="mock-radar" />,
}));

const user: ApiUser = { id: 'u1', username: 'alice', phone: null, role: 'user', created_at: '2026-08-14T10:00:00' };

const authValue = {
  isLoggedIn: true,
  user,
  login: async () => {},
  register: async () => {},
  logout: () => {},
  refreshMe: async () => {},
  onAuthExpired: () => () => {},
};

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

function stubReportsFetch(report: ApiReportDetail) {
  vi.stubGlobal('fetch', vi.fn(async (url: unknown) => {
    const u = String(url);
    if (u.includes('/reports?page=1&page_size=1')) {
      return envelope({ total: 1, page: 1, page_size: 1, items: [{ id: 'r1' }] });
    }
    if (u.includes('/reports/r1')) return envelope(report);
    return envelope(null);
  }));
}

function renderHome() {
  return render(
    <AuthContext.Provider value={authValue}>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe('HomePage 常模占位文案传参', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('标准 1：norm=null → 首页画像摘要不渲染占位文案', async () => {
    stubReportsFetch(makeReport(null));
    renderHome();

    expect(await screen.findByText('82')).toBeInTheDocument();
    expect(screen.getByText('综合竞争力评分')).toBeInTheDocument();
    expect(screen.queryByText('当前样本量不足，暂不展示同届分位')).not.toBeInTheDocument();
    expect(screen.queryByText('基于预置常模基准，非真实用户池')).not.toBeInTheDocument();
    expect(screen.queryByText(/处于参考样本/)).not.toBeInTheDocument();
  });

  it('标准 2：norm 非 null 且 band/note 存在 → 正常传参渲染（不丢失展示）', async () => {
    stubReportsFetch(
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
    renderHome();

    expect(await screen.findByText('处于参考样本前 25%')).toBeInTheDocument();
    expect(screen.getByText('常模样本可能含在职人员')).toBeInTheDocument();
  });

  it('标准 2：norm 非 null 但 band=null/note=null（后端当前形态）→ 不传占位文案', async () => {
    stubReportsFetch(
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
    renderHome();

    await waitFor(() => expect(screen.getByText('82')).toBeInTheDocument());
    expect(screen.queryByText('当前样本量不足，暂不展示同届分位')).not.toBeInTheDocument();
    expect(screen.queryByText('基于预置常模基准，非真实用户池')).not.toBeInTheDocument();
    expect(screen.queryByText(/处于参考样本/)).not.toBeInTheDocument();
  });
});
