/* ：我的计划页顶部多维度进度 + 成果覆盖任务展示
   标准 1：任务覆盖计入有效完成数，顶部展示「完成 x/y · 成果 n · 阶段通过 m/3」
   标准 2：存量计划无 achievements / covered_by_achievement 时优雅降级，计数为 0 或不渲染，不抛异常 */
import { render, screen } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MyPlanPage from './MyPlanPage';
import { AuthContext } from '../stores/useAuthStore';
import { LoginModalContext } from '../hooks/useLoginModal';
import { feedbackApi } from '../services/feedbackApi';
import type { ApiPlanDetail, ApiUser } from '../types';

vi.mock('../services/feedbackApi', () => ({
  feedbackApi: {
    getPlan: vi.fn(),
    updateTaskStatus: vi.fn(),
    listAchievements: vi.fn(),
    createAchievement: vi.fn(),
    updateAchievement: vi.fn(),
    deleteAchievement: vi.fn(),
    requestReassessment: vi.fn(),
    getTask: vi.fn(),
    getReassessment: vi.fn(),
    applyReassessment: vi.fn(),
    discardReassessment: vi.fn(),
  },
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

const loginModalValue = {
  open: false,
  openLogin: vi.fn(),
  closeLogin: vi.fn(),
};

const coveredPlan: ApiPlanDetail = {
  id: 'p1',
  report_id: 'r1',
  gap_analysis_id: 'g1',
  created_at: '2026-08-17T10:00:00',
  updated_at: '2026-08-17T10:00:00',
  target_job: '算法工程师',
  stages: {
    short: { label: '短期（1 个月内）', tasks_count: 2, completion_check: 'pass' },
    mid: { label: '中期（1-3 个月）', tasks_count: 2, completion_check: 'fail' },
    long: { label: '长期（3 个月以上）', tasks_count: 1, completion_check: 'unchecked' },
  },
  // 模拟旧后端 progress 口径：即使为 20，前端也应基于任务/覆盖真实计算
  progress: 20,
  tasks: [
    { id: 't1', name: '完成机器学习课程', resource: 'Coursera', duration: '2 周', stage: 'short', status: 'done', sort_order: 1, acceptance_criteria: '完成课程并通过测验', covered_by_achievement: true },
    { id: 't2', name: '实现一个推荐系统', resource: 'GitHub', duration: '3 周', stage: 'short', status: 'todo', sort_order: 2, covered_by_achievement: true },
    { id: 't3', name: '学习 SQL', resource: 'LeetCode', duration: '1 周', stage: 'mid', status: 'doing', sort_order: 3, covered_by_achievement: false },
    { id: 't4', name: '完成数据分析项目', resource: 'Kaggle', duration: '2 周', stage: 'mid', status: 'done', sort_order: 4, covered_by_achievement: false },
    { id: 't5', name: '长期项目', resource: '书籍', duration: '1 月', stage: 'long', status: 'todo', sort_order: 5, covered_by_achievement: false },
  ],
  achievements: [
    { id: 'a1', name: '机器学习项目', url: 'https://example.com/1', description: null, stage: 'short', task_id: 't1', created_at: '2026-08-17T10:00:00', updated_at: '2026-08-17T10:00:00' },
    { id: 'a2', name: '推荐系统项目', url: 'https://example.com/2', description: null, stage: 'short', task_id: 't2', created_at: '2026-08-17T11:00:00', updated_at: '2026-08-17T11:00:00' },
  ],
  reassess_eligible: true,
  reassess_eligible_reason: null,
  latest_reassess: null,
};

const legacyPlan: ApiPlanDetail = {
  id: 'p2',
  report_id: 'r2',
  gap_analysis_id: 'g2',
  created_at: '2026-08-17T09:00:00',
  updated_at: '2026-08-17T09:00:00',
  target_job: '后端工程师',
  stages: {
    short: { label: '短期（1 个月内）', tasks_count: 1, completion_check: null },
    mid: { label: '中期（1-3 个月）', tasks_count: 1, completion_check: null },
    long: { label: '长期（3 个月以上）', tasks_count: 0, completion_check: null },
  },
  progress: 50,
  tasks: [
    { id: 't1', name: '任务 1', resource: '资源', duration: '1 周', stage: 'short', status: 'done', sort_order: 1 },
    { id: 't2', name: '任务 2', resource: '资源', duration: '1 周', stage: 'mid', status: 'todo', sort_order: 2 },
  ],
  reassess_eligible: false,
  reassess_eligible_reason: '请先上传成果或标记任务进度',
  latest_reassess: null,
};

function renderPage() {
  return render(
    <AuthContext.Provider value={authValue}>
      <LoginModalContext.Provider value={loginModalValue}>
        <ConfigProvider>
          <AntApp>
            <MemoryRouter initialEntries={['/my-plan?planId=p1']}>
              <MyPlanPage />
            </MemoryRouter>
          </AntApp>
        </ConfigProvider>
      </LoginModalContext.Provider>
    </AuthContext.Provider>,
  );
}

describe('MyPlanPage 计划反馈打通展示', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    window.history.replaceState({}, '', '/my-plan?planId=p1');
  });

  it('标准 1：顶部展示多维度进度（完成 x/y · 成果 n · 阶段通过 m/3），覆盖任务计入有效完成数', async () => {
    vi.mocked(feedbackApi.getPlan).mockResolvedValue(coveredPlan);
    renderPage();

    expect(await screen.findByText('目标岗位：算法工程师')).toBeInTheDocument();
    expect(screen.getByText('完成 3/5 项 · 成果 2 · 阶段通过 1/3')).toBeInTheDocument();
    // 覆盖任务渲染“已由成果覆盖”标签（多成果覆盖多任务：标签按任务数，不按成果数）
    expect(screen.getAllByText('已由成果覆盖')).toHaveLength(2);
    // 前端按 done ∪ covered 计算进度（3/5 = 60%），不使用旧后端 progress=20
    expect(screen.getByText('60%')).toBeInTheDocument();
  });

  it('标准 2：一个任务多个成果时覆盖仍只计一次，顶部不虚增完成数，标签不重复', async () => {
    const multiAchievementsOneTask: ApiPlanDetail = {
      ...coveredPlan,
      progress: 100,
      tasks: [
        { id: 't1', name: '完成机器学习课程', resource: 'Coursera', duration: '2 周', stage: 'short', status: 'todo', sort_order: 1, acceptance_criteria: '完成课程并通过测验', covered_by_achievement: true },
        { id: 't4', name: '完成数据分析项目', resource: 'Kaggle', duration: '2 周', stage: 'short', status: 'done', sort_order: 2, acceptance_criteria: null, covered_by_achievement: false },
      ],
      achievements: [
        { id: 'a1', name: '机器学习项目', url: 'https://example.com/1', description: null, stage: 'short', task_id: 't1', created_at: '2026-08-17T10:00:00', updated_at: '2026-08-17T10:00:00' },
        { id: 'a2', name: '机器学习项目二', url: 'https://example.com/2', description: null, stage: 'short', task_id: 't1', created_at: '2026-08-17T11:00:00', updated_at: '2026-08-17T11:00:00' },
      ],
    };
    vi.mocked(feedbackApi.getPlan).mockResolvedValue(multiAchievementsOneTask);
    renderPage();

    expect(await screen.findByText('目标岗位：算法工程师')).toBeInTheDocument();
    // 2 条成果都关联 t1，但有效完成仍是 {t1 覆盖, t4 done} = 2/2
    expect(screen.getByText('完成 2/2 项 · 成果 2 · 阶段通过 1/3')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getAllByText('已由成果覆盖')).toHaveLength(1);
  });

  it('标准 2：存量计划无 achievements / covered_by_achievement 时优雅降级，不渲染“成果 0”且无覆盖标签', async () => {
    vi.mocked(feedbackApi.getPlan).mockResolvedValue(legacyPlan);
    renderPage();

    expect(await screen.findByText('目标岗位：后端工程师')).toBeInTheDocument();
    expect(screen.getByText('完成 1/2 项 · 阶段通过 0/3')).toBeInTheDocument();
    expect(screen.queryByText(/成果 0/)).not.toBeInTheDocument();
    expect(screen.queryByText('已由成果覆盖')).not.toBeInTheDocument();
  });

  it('标准 2：achievements 显式空数组时展示“成果 0”（计数诚实）', async () => {
    vi.mocked(feedbackApi.getPlan).mockResolvedValue({ ...legacyPlan, achievements: [] });
    renderPage();

    expect(await screen.findByText('目标岗位：后端工程师')).toBeInTheDocument();
    expect(screen.getByText('完成 1/2 项 · 成果 0 · 阶段通过 0/3')).toBeInTheDocument();
  });
});
