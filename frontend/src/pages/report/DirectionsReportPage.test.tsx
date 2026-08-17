/* ：方向卡片薪资对比——DirectionsReportPage（spot 1）
   标准 1/2：mock 数据下方向卡片渲染薪资对比行（复用 SalaryComparison）
   标准 3：null → 整块隐藏；no_data → 只渲染 note「暂无该岗位薪资数据」 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ConfigProvider, App as AntApp } from 'antd';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import DirectionsReportPage from './DirectionsReportPage';
import { mockSalaryComparisonDirections } from '../../services/mockData';
import type { ApiReportDetail } from '../../types';

function makeReport(directionId: string): ApiReportDetail {
  const direction = mockSalaryComparisonDirections.find((d) => d.id === directionId);
  if (!direction) throw new Error(`mock direction ${directionId} 不存在`);
  return {
    id: 'r1',
    stage: 'stage1',
    status: 'completed',
    portrait: null,
    directions: [direction],
    gap_analysis: null,
    plan: null,
    created_at: '2026-08-15T10:00:00',
    finished_at: null,
  };
}

const envelope = (data: unknown) => ({
  status: 200,
  json: async () => ({ code: 0, message: 'ok', data }),
});

function renderDirections(report: ApiReportDetail) {
  vi.stubGlobal('fetch', vi.fn(async (url: unknown) => {
    const u = String(url);
    if (u.includes('/reports/r1')) return envelope(report);
    return envelope(null);
  }));
  return render(
    <ConfigProvider>
      <AntApp>
        <MemoryRouter initialEntries={['/report/directions?reportId=r1']}>
          <DirectionsReportPage />
        </MemoryRouter>
      </AntApp>
    </ConfigProvider>,
  );
}

describe('DirectionsReportPage 薪资对比行', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('标准 1：salary_comparison 有数据 → 渲染徽标 + note（复用 SalaryComparison）', async () => {
    renderDirections(makeReport('mock-salary-p50-p75'));

    expect(await screen.findByText('市场 50-75 分位')).toBeInTheDocument();
    expect(screen.getByText('演示岗位·50-75 分位')).toBeInTheDocument();
    expect(screen.getByText(/50-75 分位段/)).toBeInTheDocument();
  });

  it('标准 3：salary_comparison=null → 不渲染对比行（整块隐藏）', async () => {
    renderDirections(makeReport('mock-salary-null'));

    expect(await screen.findByText('演示岗位·无期望薪资')).toBeInTheDocument();
    expect(screen.queryByText('市场 50-75 分位')).not.toBeInTheDocument();
    expect(screen.queryByText('低于市场 25 分位')).not.toBeInTheDocument();
    expect(screen.queryByText(/暂无该岗位薪资数据/)).not.toBeInTheDocument();
  });

  it('标准 3：level=no_data → 只渲染 note「暂无该岗位薪资数据」，无徽标', async () => {
    renderDirections(makeReport('mock-salary-no-data'));

    expect(await screen.findByText('暂无该岗位薪资数据')).toBeInTheDocument();
    expect(screen.queryByText('市场 50-75 分位')).not.toBeInTheDocument();
    expect(screen.queryByText('高于市场 75 分位')).not.toBeInTheDocument();
  });
});
