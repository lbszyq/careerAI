/* ：重评结果中「已具备」不再以「仍存在」危险语义展示
   标准 3：level=已具备 的项从“仍存在”中分离，标注「已具备（无需补齐）」；测试明确断言 */
import { render, screen } from '@testing-library/react';
import { App as AntApp, ConfigProvider } from 'antd';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ReassessResultDrawer from './ReassessResultDrawer';
import { feedbackApi } from '../../services/feedbackApi';
import type { ApiReassessmentDetail } from '../../types';

vi.mock('../../services/feedbackApi', () => ({
  feedbackApi: {
    getReassessment: vi.fn(),
    applyReassessment: vi.fn(),
    discardReassessment: vi.fn(),
  },
}));

const baseDetail: ApiReassessmentDetail = {
  id: 'ra1',
  plan_id: 'p1',
  task_id: 'task1',
  status: 'completed',
  decision: 'undecided',
  summary: '重评摘要',
  gap_change: {
    summary: '已补齐：无；仍存在：SQL、Python',
    resolved_items: [],
    remaining_items: [
      { skill: 'SQL', level: '已具备', confidence: 'high', evidence_refs: [] },
      { skill: 'Python', level: '不具备', confidence: 'medium', evidence_refs: [] },
    ],
  },
  plan_adjustment: { summary: '无调整', changes: [], conflicts: [] },
  stage_checks: {
    short: { result: 'pass', reason: '短期通过', suggestion: null, stay: false },
    mid: { result: 'fail', reason: '中期未通过', suggestion: '补齐 Python', stay: true },
    long: { result: 'fail', reason: '长期未通过', suggestion: null, stay: true },
  },
  adjustment_explanation: { summary: '调整说明', evidence_refs: [] },
  created_at: '2026-08-17T10:00:00',
  decided_at: null,
};

function renderDrawer(detail: ApiReassessmentDetail) {
  vi.mocked(feedbackApi.getReassessment).mockResolvedValue(detail);
  return render(
    <ConfigProvider>
      <AntApp>
        <ReassessResultDrawer
          open
          planId="p1"
          reassessId="ra1"
          onClose={() => {}}
          onDecided={() => {}}
        />
      </AntApp>
    </ConfigProvider>,
  );
}

describe('ReassessResultDrawer 已具备与仍存在分离', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('标准 3：level=已具备 的项标注「已具备（无需补齐）」，不再计入「仍存在」', async () => {
    renderDrawer(baseDetail);

    expect(await screen.findByText('SQL')).toBeInTheDocument();
    expect(screen.getByText('已具备（无需补齐）')).toBeInTheDocument();
    expect(screen.getByText('Python')).toBeInTheDocument();
    // 只有 Python 一条仍以「仍存在」展示
    expect(screen.getAllByText('仍存在')).toHaveLength(1);
  });

  it('标准 3：全部剩余项均为已具备时不渲染「仍存在」', async () => {
    renderDrawer({
      ...baseDetail,
      gap_change: {
        ...baseDetail.gap_change,
        remaining_items: [
          { skill: 'SQL', level: '已具备', confidence: 'high', evidence_refs: [] },
          { skill: 'Docker', level: '已具备', confidence: null, evidence_refs: [] },
        ],
      },
    });

    expect(await screen.findByText('SQL')).toBeInTheDocument();
    expect(screen.getAllByText('已具备（无需补齐）')).toHaveLength(2);
    expect(screen.queryByText('仍存在')).not.toBeInTheDocument();
  });

  it('标准 3：level=undefined 的剩余项仍按「仍存在」展示（不误判为已具备）', async () => {
    renderDrawer({
      ...baseDetail,
      gap_change: {
        ...baseDetail.gap_change,
        remaining_items: [
          { skill: 'Git', level: undefined, confidence: null, evidence_refs: [] },
          { skill: 'SQL', level: '已具备', confidence: 'high', evidence_refs: [] },
        ],
      },
    });

    expect(await screen.findByText('Git')).toBeInTheDocument();
    expect(screen.getAllByText('仍存在')).toHaveLength(1);
    expect(screen.getByText('已具备（无需补齐）')).toBeInTheDocument();
  });
});
