import { describe, expect, it } from 'vitest';

import {
  toCareerDirection,
  toGapItem,
  toGapWeight,
  toPlanTask,
  toReportSummary,
} from './adapters';

const baseDirection = {
  id: 'd1',
  job_title: '前端工程师',
  match_score: 92,
  salary: null,
  salary_note: null,
  trend: null,
  heat: null,
  data_source: null,
  education_requirement: null,
  education_match: null,
  competition_note: null,
  certificates_bonus: null,
  recommend_reason: null,
};

describe('toCareerDirection 方向适配器', () => {
  it('薪资单位换算：元/月 → k/月（除以 1000，保留 1 位小数）', () => {
    const dir = toCareerDirection({
      ...baseDirection,
      salary: { p25: 12500, p50: 18000, p75: 24000 },
      trend: '增长',
      heat: '高',
    });

    expect(dir.salaryMin).toBe(12.5);
    expect(dir.salaryMedian).toBe(18);
    expect(dir.salaryMax).toBe(24);
    expect(dir.boxplot).toEqual({ min: 12.5, q1: 12.5, median: 18, q3: 24, max: 24 });
    expect(dir.trend).toBe('growth');
    expect(dir.heat).toBe('high');
  });

  it('薪资为空时降级为 0，不抛错（边界）', () => {
    const dir = toCareerDirection(baseDirection);

    expect(dir.salaryMin).toBe(0);
    expect(dir.salaryMedian).toBe(0);
    expect(dir.salaryMax).toBe(0);
    expect(dir.boxplot).toEqual({ min: 0, q1: 0, median: 0, q3: 0, max: 0 });
  });

  it('透传 salary_comparison 到展示类型（只透传 level + note）', () => {
    const dir = toCareerDirection({
      ...baseDirection,
      salary_comparison: {
        expected_salary: 12000,
        p25: 8000,
        p50: 12000,
        p75: 18000,
        level: 'p50_p75',
        note: '你的期望薪资处于 50-75 分位段',
      },
    });

    expect(dir.salaryComparison).toEqual({
      level: 'p50_p75',
      note: '你的期望薪资处于 50-75 分位段',
    });
  });

  it('salary_comparison=null → salaryComparison 为 null（前端隐藏）', () => {
    const dir = toCareerDirection({ ...baseDirection, salary_comparison: null });
    expect(dir.salaryComparison).toBeNull();
  });

  it('salary_comparison 字段缺失（旧接口兼容）→ salaryComparison 为 null 不崩溃', () => {
    const dir = toCareerDirection(baseDirection);
    expect(dir.salaryComparison).toBeNull();
  });
});

describe('toGapWeight 差距权重适配', () => {
  it('边界值：≥0.2 → high，≥0.1 → medium，<0.1 → low', () => {
    expect(toGapWeight(0.2)).toBe('high');
    expect(toGapWeight(0.19)).toBe('medium');
    expect(toGapWeight(0.1)).toBe('medium');
    expect(toGapWeight(0.09)).toBe('low');
  });

  it('非有限数字防御性兜底为 low', () => {
    expect(toGapWeight(NaN)).toBe('low');
    expect(toGapWeight(Infinity)).toBe('low');
  });
});

describe('toPlanTask 计划任务适配器', () => {
  it('todo → pending，doing/done 原样透传', () => {
    expect(toPlanTask({ id: 't1', name: '任务', resource: null, duration: null, stage: 'short', status: 'todo', sort_order: 1 }).status).toBe('pending');
    expect(toPlanTask({ id: 't2', name: '任务', resource: null, duration: null, stage: 'short', status: 'doing', sort_order: 2 }).status).toBe('doing');
    expect(toPlanTask({ id: 't3', name: '任务', resource: null, duration: null, stage: 'short', status: 'done', sort_order: 3 }).status).toBe('done');
  });

  it('covered_by_achievement 透传，缺省视为 false', () => {
    expect(toPlanTask({ id: 't1', name: '任务', resource: null, duration: null, stage: 'short', status: 'todo', sort_order: 1, covered_by_achievement: true }).coveredByAchievement).toBe(true);
    expect(toPlanTask({ id: 't2', name: '任务', resource: null, duration: null, stage: 'short', status: 'todo', sort_order: 2 }).coveredByAchievement).toBe(false);
  });
});

describe('toReportSummary 报告列表适配器', () => {
  it('stage2 报告映射为 4 类，target_job 优先于 job_titles[0]', () => {
    const summary = toReportSummary({
      id: 'r1',
      stage: 'stage2',
      status: 'completed',
      score: 85,
      created_at: '2026-08-09T10:30:00',
      summary: { job_titles: ['后端工程师'], target_job: '全栈工程师' },
    });

    expect(summary.types).toEqual(['portrait', 'directions', 'gap', 'plan']);
    expect(summary.direction).toBe('全栈工程师');
    expect(summary.date).toBe('2026-08-09 10:30');
  });

  it('stage1 报告映射为 2 类，缺失 target_job 时兜底 job_titles[0]（边界）', () => {
    const summary = toReportSummary({
      id: 'r2',
      stage: 'stage1',
      status: 'running',
      score: null,
      created_at: '2026-08-09T10:30:00',
      summary: { job_titles: ['后端工程师'] },
    });

    expect(summary.types).toEqual(['portrait', 'directions']);
    expect(summary.direction).toBe('后端工程师');
    expect(summary.status).toBe('running');
    expect(summary.score).toBe(0);
  });
});

describe('toGapItem 差距项适配器', () => {
  it('level 中文映射为展示 status，未知枚举兜底 partial', () => {
    expect(
      toGapItem({ skill: 'Python', weight: 0.3, level: '具备', jd_source: '', evidence: '' }).status,
    ).toBe('have');
    expect(
      toGapItem({ skill: 'Python', weight: 0.15, level: '部分具备', jd_source: '', evidence: '' }).status,
    ).toBe('partial');
    expect(
      toGapItem({ skill: 'Python', weight: 0.05, level: '不具备', jd_source: '', evidence: '' }).status,
    ).toBe('lack');
    expect(
      toGapItem({ skill: 'Python', weight: 0.1, level: '未知等级', jd_source: '', evidence: '' }).status,
    ).toBe('partial');
  });
});

