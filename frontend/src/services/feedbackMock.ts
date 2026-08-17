/* ============================================================
   反馈闭环契约 Mock（专用；后端 未合入 develop 前使用）
   - 边界：仅限 PRD/契约定义字段；重评四部分 mock 与 feedback-contract
     重评详情 schema 完全一致
   - 持久化：localStorage（键 careerai:feedback_mock）——离开页面/刷新后
     任务状态与重评记录保持一致（支撑「离开返回仍在」验证）
   - 切换：VITE_FEEDBACK_MOCK=true 时 feedbackApi 门面走本文件；
     后端合入后设 false 即切真实 API（零代码改动）
   ============================================================ */
import { ApiClientError } from './http';
import type {
  ApiAchievement,
  ApiAchievementDeleteResult,
  ApiAchievementList,
  ApiAchievementUpsert,
  ApiEvidenceRef,
  ApiPlanDetail,
  ApiPlanTaskStatus,
  ApiReassessAccepted,
  ApiReassessDecision,
  ApiReassessmentDetail,
  ApiTaskJob,
  ApiTaskStatus,
} from '../types';
import type { PlanTaskStatusResult } from './plansApi';

const STORAGE_KEY = 'careerai:feedback_mock';
const PLAN_ID = 'plan-feedback-demo';
const REASSESS_TASK_SECONDS = 6; // mock 重评时长（秒）：>6s 转 succeeded（配合 5s 轮询，第三次轮询命中；保证「离开返回仍在」可观察）

/* ---------- mock 内部状态类型 ---------- */

interface MockTask {
  id: string;
  task_type: 'plan_reassess';
  status: ApiTaskStatus;
  progress: number;
  stage: string | null;
  result_ref: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
  startedAt: number;
  reassessId: string | null;
}

interface MockReassessRecord {
  id: string;
  task_id: string;
  status: 'succeeded';
  decision: 'undecided' | 'applied' | 'discarded';
  summary: string;
  created_at: string;
  decided_at: string | null;
}

interface MockState {
  plan: ApiPlanDetail;
  achievements: ApiAchievement[];
  reassessments: MockReassessRecord[];
  tasks: Record<string, MockTask>;
  reassessSeq: number;
}

/* ---------- 种子数据（契约字段内；四部分结构对齐 feedback-contract） ---------- */

const nowIso = () => new Date().toISOString();
const isoAdd = (iso: string, minutes: number) => new Date(new Date(iso).getTime() + minutes * 60_000).toISOString();

function buildSeedState(): MockState {
  const created = '2026-08-08T10:00:00+08:00';
  const achievements: ApiAchievement[] = [
    {
      id: 'ach-seed-1',
      name: 'SQL 数据分析项目',
      url: 'https://github.com/example/sql-analysis',
      description: '完成窗口函数专项，产出可视化看板',
      stage: 'short',
      task_id: 'task-seed-1',
      created_at: '2026-08-08T10:00:00+08:00',
      updated_at: '2026-08-08T10:00:00+08:00',
    },
  ];

  const plan: ApiPlanDetail = {
    id: PLAN_ID,
    report_id: 'report-seed-1',
    gap_analysis_id: 'gap-seed-1',
    target_job: '数据分析师',
    stages: {
      short: {
        label: '短期（1 个月内）',
        tasks_count: 2,
        goal: '掌握 SQL 窗口函数与数据分析基础工具，达到可独立取数分析的水平',
        why: '目标岗位 JD 要求：熟练使用 SQL 完成数据提取与分析',
        verify: '完成 1 个端到端数据分析项目（技术产出：SQL+可视化；工程产出：项目可运行/已部署；业务产出：输出 1 份可解读的分析结论）',
        resume_value: '可写入简历：独立完成 XX 数据分析项目，沉淀 SQL 取数与可视化能力',
        stage_completion: '完成判定：项目产出验证通过 / 部署成功 / GitHub 提交记录，满足后进入下一阶段',
        completion_check: 'pass',
      },
      mid: {
        label: '中期（1-3 个月）',
        tasks_count: 2,
        goal: '掌握数据建模与特征工程基础，能独立完成业务建模',
        why: '目标岗位 JD 要求：具备数据建模与业务分析能力',
        verify: '完成 1 个端到端建模项目（含特征工程、模型评估与结论输出）',
        resume_value: '可写入简历：完成 XX 建模项目，沉淀特征工程与模型评估能力',
        stage_completion: '完成判定：建模项目验证通过 / 模型评估报告输出，满足后进入下一阶段',
        completion_check: 'fail',
      },
      long: {
        label: '长期（3 个月以上）',
        tasks_count: 2,
        goal: '具备独立负责数据专项的能力，形成可复用的分析方法论',
        why: '目标岗位 JD 要求：能独立承担数据专项并输出可落地方案',
        verify: '沉淀可复用的分析/建模方法论文档',
        resume_value: '可写入简历：形成可复用的数据分析方法论',
        stage_completion: '完成判定：方法论文档沉淀 / 专项复盘通过，满足后进入下一阶段',
        completion_check: 'unchecked',
      },
    },
    progress: 33,
    tasks: [
      { id: 'task-seed-1', name: '完成 SQL 窗口函数专项练习', resource: '《SQL 必知必会》第 8-10 章 / LeetCode SQL 题库', duration: '2 周', stage: 'short', status: 'done', sort_order: 1, acceptance_criteria: '能独立完成窗口函数相关 3 道 LeetCode 题目并通过' },
      { id: 'task-seed-2', name: '搭建个人数据分析作品集项目', resource: 'Kaggle 公开数据集 + GitHub', duration: '1 个月', stage: 'short', status: 'doing', sort_order: 2, acceptance_criteria: '项目可运行并部署，附 GitHub 提交记录' },
      { id: 'task-seed-3', name: '数据清洗练习（将并入数据建模专项）', resource: 'Pandas 官方文档 + 真实脏数据', duration: '2 周', stage: 'mid', status: 'todo', sort_order: 3, acceptance_criteria: '完成 1 份数据清洗报告' },
      { id: 'task-seed-4', name: '完成数据建模专项练习', resource: 'sklearn 官方教程 + 公开数据集', duration: '1 个月', stage: 'mid', status: 'todo', sort_order: 4, acceptance_criteria: '完成 1 个端到端建模项目并输出评估报告' },
      { id: 'task-seed-5', name: '沉淀分析方法论文档', resource: 'Notion / 个人博客', duration: '1 个月', stage: 'long', status: 'todo', sort_order: 5, acceptance_criteria: '输出 1 份可复用的分析方法论文档' },
      { id: 'task-seed-6', name: '完成专项复盘与简历更新', resource: '简历模板 + 项目复盘', duration: '2 周', stage: 'long', status: 'todo', sort_order: 6, acceptance_criteria: '更新简历并完成 1 次专项复盘' },
    ],
    achievements,
    reassess_eligible: true,
    reassess_eligible_reason: null,
    latest_reassess: {
      task_id: 'task-seed-reassess-1',
      status: 'succeeded',
      result_ref: `/api/v1/plans/${PLAN_ID}/reassessments/ra-seed-1`,
      created_at: '2026-08-08T11:00:00+08:00',
      finished_at: '2026-08-08T11:02:40+08:00',
    },
    created_at: created,
    updated_at: isoAdd(created, 30),
  };

  const reassessments: MockReassessRecord[] = [
    {
      id: 'ra-seed-1',
      task_id: 'task-seed-reassess-1',
      status: 'succeeded',
      decision: 'applied',
      summary: '差距缩小 2 项，短期阶段校验通过，计划调整 3 项',
      created_at: '2026-08-08T11:00:00+08:00',
      decided_at: '2026-08-08T11:10:00+08:00',
    },
  ];

  return { plan, achievements, reassessments, tasks: {}, reassessSeq: 1 };
}

/* ---------- 持久化 ---------- */

function loadState(): MockState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as MockState;
      if (parsed && parsed.plan && parsed.plan.id === PLAN_ID) return parsed;
    }
  } catch {
    /* 损坏则重建 */
  }
  const fresh = buildSeedState();
  saveState(fresh);
  return fresh;
}

function saveState(state: MockState): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* 隐私模式等场景静默降级为内存态 */
  }
}

/** 进度重算：done 任务占比（契约口径） */
function recalcProgress(state: MockState): number {
  const tasks = state.plan.tasks;
  if (tasks.length === 0) return 0;
  return Math.round((tasks.filter((t) => t.status === 'done').length / tasks.length) * 100);
}

/** 重评前置判定：成果数 ≥1 或存在非 todo 任务 */
function recalcEligible(state: MockState): void {
  const hasAchievement = state.achievements.length >= 1;
  const hasProgress = state.plan.tasks.some((t) => t.status !== 'todo');
  state.plan.reassess_eligible = hasAchievement || hasProgress;
  state.plan.reassess_eligible_reason = state.plan.reassess_eligible
    ? null
    : '请先上传成果或标记任务进度';
}

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** 构造四部分重评详情（schema 对齐 feedback-contract） */
function buildReassessmentDetail(state: MockState, record: MockReassessRecord): ApiReassessmentDetail {
  const evidence: ApiEvidenceRef[] = state.achievements.map((a) => ({
    type: 'achievement',
    id: a.id,
    name: a.name,
    url: a.url,
  }));
  return {
    id: record.id,
    plan_id: PLAN_ID,
    task_id: record.task_id,
    status: 'succeeded',
    decision: record.decision,
    summary: record.summary,
    gap_change: {
      summary: '已补齐：SQL 窗口函数；仍存在：数据建模与工程化',
      resolved_items: [
        {
          skill: 'SQL 窗口函数',
          evidence_refs: evidence.filter((e) => e.id === 'ach-seed-1').length > 0
            ? evidence.filter((e) => e.id === 'ach-seed-1')
            : [{ type: 'achievement', id: 'ach-seed-1', name: 'SQL 数据分析项目', url: 'https://github.com/example/sql-analysis' }],
        },
      ],
      remaining_items: [
        { skill: '数据建模', level: '部分具备', confidence: 'medium', evidence_refs: [] },
        { skill: '工程化能力', level: '不具备', confidence: 'low', evidence_refs: [] },
      ],
    },
    plan_adjustment: {
      summary: '短期阶段新增 1 项任务，中期目标描述微调，移除 1 项重复任务',
      changes: [
        {
          action: 'add',
          target: 'task',
          stage: 'short',
          task_id: null,
          name: '完成数据建模专项练习',
          reason: '重评发现数据建模仍为差距项',
          evidence_refs: evidence,
        },
        {
          action: 'modify',
          target: 'stage',
          stage: 'mid',
          task_id: null,
          name: null,
          reason: '中期目标与已补齐能力不一致，收敛范围',
          evidence_refs: [],
        },
        {
          action: 'remove',
          target: 'task',
          stage: 'mid',
          task_id: 'task-seed-3',
          name: '数据清洗练习（已并入数据建模专项）',
          reason: '与新增任务重复',
          evidence_refs: [],
        },
      ],
      conflicts: [
        {
          task_id: 'task-seed-3',
          task_name: '数据清洗练习',
          note: 'AI 建议回退该任务状态，与用户已完成标记冲突，保留用户完成为准',
        },
      ],
    },
    stage_checks: {
      short: { result: 'pass', reason: '阶段项目已部署且有 GitHub 提交记录', suggestion: null, stay: false },
      mid: { result: 'fail', reason: '尚未产出可验证的建模项目成果', suggestion: '先完成 1 个端到端建模项目并上传成果，再申请重评', stay: true },
      long: { result: 'fail', reason: '距离长期目标仍有明显差距，当前无对应成果', suggestion: '按中期阶段补齐后再评估', stay: true },
    },
    adjustment_explanation: {
      summary: '本次调整基于 2 条成果与 3 项任务状态证据：SQL 能力已补齐，数据建模成为主要差距项',
      evidence_refs: evidence,
    },
    created_at: record.created_at,
    decided_at: record.decided_at,
  };
}

/** 任务状态推进（时间驱动：<3s running / 3-6s running 推进 / ≥6s succeeded） */
function advanceTask(state: MockState, task: MockTask): void {
  const elapsed = (Date.now() - task.startedAt) / 1000;
  const now = nowIso();
  if (task.status === 'succeeded' || task.status === 'failed') {
    task.updated_at = now;
    return;
  }
  if (elapsed >= REASSESS_TASK_SECONDS) {
    // 成功落库：生成重评记录 + 更新计划回显（latest_reassess / completion_check）
    task.status = 'succeeded';
    task.progress = 100;
    task.stage = '完成';
    task.finished_at = now;
    const reassessId = `ra-${state.reassessSeq++}`;
    task.reassessId = reassessId;
    task.result_ref = `/api/v1/plans/${PLAN_ID}/reassessments/${reassessId}`;
    const record: MockReassessRecord = {
      id: reassessId,
      task_id: task.id,
      status: 'succeeded',
      decision: 'undecided',
      summary: '差距缩小 1 项，中期阶段校验未通过，计划调整 3 项',
      created_at: now,
      decided_at: null,
    };
    state.reassessments.unshift(record);
    state.plan.latest_reassess = {
      task_id: task.id,
      status: 'succeeded',
      result_ref: task.result_ref,
      created_at: task.created_at,
      finished_at: now,
    };
    state.plan.stages.short.completion_check = 'pass';
    state.plan.stages.mid.completion_check = 'fail';
    state.plan.stages.long.completion_check = 'unchecked';
    state.plan.updated_at = now;
  } else if (elapsed >= 3) {
    task.status = 'running';
    task.progress = 60;
    task.stage = '正在校验阶段完成情况…';
    task.updated_at = now;
  } else {
    task.status = 'running';
    task.progress = 20;
    task.stage = '正在根据您的成果重新评估…';
    task.updated_at = now;
  }
}

/* ---------- 反馈闭环 Mock API（与真实 API 同接口，供 feedbackApi 门面切换） ---------- */

export const feedbackMock = {
  /** PATCH /plans/{plan_id}/tasks/{task_id}：任务状态更新（进度/前置重算，幂等） */
  async updateTaskStatus(planId: string, taskId: string, status: ApiPlanTaskStatus): Promise<PlanTaskStatusResult> {
    await delay(150);
    const state = loadState();
    const task = state.plan.tasks.find((t) => t.id === taskId);
    if (!task) throw new ApiClientError(4106, '计划任务不存在', 404);
    task.status = status;
    state.plan.progress = recalcProgress(state);
    recalcEligible(state);
    saveState(state);
    return { plan_id: planId, task_id: taskId, task_status: status, progress: state.plan.progress };
  },

  /** GET /plans/{plan_id}：计划详情（mock 整体接管，保证反馈回显字段一致） */
  async getPlan(_planId: string): Promise<ApiPlanDetail> {
    await delay(200);
    const state = loadState();
    // 同步任务状态到计划回显（进行中任务：latest_reassess 显示进行中）
    const running = Object.values(state.tasks).find((t) => t.status === 'running' || t.status === 'pending');
    if (running) {
      advanceTask(state, running);
      if (running.status === 'succeeded') {
        // 已处理，latest_reassess 已更新
      } else {
        state.plan.latest_reassess = {
          task_id: running.id,
          status: running.status as 'running',
          result_ref: null,
          created_at: running.created_at,
          finished_at: null,
        };
      }
      saveState(state);
    }
    const plan = JSON.parse(JSON.stringify(state.plan)) as ApiPlanDetail;
    // 成果以 state.achievements 为唯一数据源（JSON 持久化后引用断裂，返回前同步）；
    // 存量计划（持久化中 achievements 字段缺失）保持缺失 → 前端隐藏成果区
    if (plan.achievements !== undefined) {
      plan.achievements = state.achievements.map((a) => ({ ...a }));
    }
    return plan;
  },

  /** GET /plans/{plan_id}/achievements：成果列表（创建时间倒序） */
  async listAchievements(_planId: string): Promise<ApiAchievementList> {
    await delay(150);
    const state = loadState();
    const items = [...state.achievements].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    return { plan_id: _planId, items: JSON.parse(JSON.stringify(items)) as ApiAchievement[] };
  },

  /** POST /plans/{plan_id}/achievements：上传成果 */
  async createAchievement(_planId: string, payload: ApiAchievementUpsert): Promise<ApiAchievement> {
    await delay(250);
    const state = loadState();
    const created = nowIso();
    const item: ApiAchievement = {
      id: `ach-${state.reassessSeq++}-${Date.now().toString(36)}`,
      name: payload.name,
      url: payload.url,
      description: payload.description ?? null,
      stage: payload.stage ?? null,
      task_id: payload.task_id ?? null,
      created_at: created,
      updated_at: created,
    };
    state.achievements.unshift(item);
    recalcEligible(state);
    state.plan.updated_at = created;
    saveState(state);
    return JSON.parse(JSON.stringify(item)) as ApiAchievement;
  },

  /** PATCH /plans/{plan_id}/achievements/{achievement_id}：编辑成果 */
  async updateAchievement(_planId: string, achievementId: string, payload: Partial<ApiAchievementUpsert>): Promise<ApiAchievement> {
    await delay(250);
    const state = loadState();
    const item = state.achievements.find((a) => a.id === achievementId);
    if (!item) throw new ApiClientError(4109, '成果不存在或不属于该计划', 404);
    if (payload.name !== undefined) item.name = payload.name;
    if (payload.url !== undefined) item.url = payload.url;
    if (payload.description !== undefined) item.description = payload.description ?? null;
    if (payload.stage !== undefined) item.stage = payload.stage ?? null;
    if (payload.task_id !== undefined) item.task_id = payload.task_id ?? null;
    item.updated_at = nowIso();
    recalcEligible(state);
    saveState(state);
    return JSON.parse(JSON.stringify(item)) as ApiAchievement;
  },

  /** DELETE /plans/{plan_id}/achievements/{achievement_id}：删除成果 */
  async deleteAchievement(_planId: string, achievementId: string): Promise<ApiAchievementDeleteResult> {
    await delay(200);
    const state = loadState();
    const idx = state.achievements.findIndex((a) => a.id === achievementId);
    if (idx < 0) throw new ApiClientError(4109, '成果不存在或不属于该计划', 404);
    state.achievements.splice(idx, 1);
    recalcEligible(state);
    saveState(state);
    return { id: achievementId, deleted: true };
  },

  /** POST /plans/{plan_id}/reassessments：申请重新评估（异步受理；3403 防并发） */
  async requestReassessment(_planId: string): Promise<ApiReassessAccepted> {
    await delay(300);
    const state = loadState();
    if (state.plan.reassess_eligible === false) {
      throw new ApiClientError(3402, '请先上传成果或标记任务进度', 400);
    }
    const existing = Object.values(state.tasks).find((t) => t.status === 'running' || t.status === 'pending');
    if (existing) {
      throw new ApiClientError(3403, '该计划已有进行中的重评任务，请稍候', 409);
    }
    const created = nowIso();
    const taskId = `task-reassess-${Date.now().toString(36)}`;
    const task: MockTask = {
      id: taskId,
      task_type: 'plan_reassess',
      status: 'running',
      progress: 20,
      stage: '正在根据您的成果重新评估…',
      result_ref: null,
      error_message: null,
      created_at: created,
      updated_at: created,
      finished_at: null,
      startedAt: Date.now(),
      reassessId: null,
    };
    state.tasks[taskId] = task;
    state.plan.latest_reassess = {
      task_id: taskId,
      status: 'running',
      result_ref: null,
      created_at: created,
      finished_at: null,
    };
    saveState(state);
    return { task_id: taskId, status: 'running' };
  },

  /** GET /tasks/{task_id}：任务状态轮询（mock 时间驱动推进） */
  async getTask(taskId: string): Promise<ApiTaskJob> {
    await delay(100);
    const state = loadState();
    const task = state.tasks[taskId];
    if (!task) throw new ApiClientError(4001, '任务不存在', 404);
    advanceTask(state, task);
    saveState(state);
    const job: ApiTaskJob = {
      id: task.id,
      task_type: task.task_type,
      status: task.status,
      progress: task.progress,
      stage: task.stage,
      result_ref: task.result_ref,
      result: null,
      error_message: task.error_message,
      created_at: task.created_at,
      updated_at: task.updated_at,
      finished_at: task.finished_at,
    };
    return job;
  },

  /** GET /plans/{plan_id}/reassessments/{reassess_id}：重评结果详情（四部分） */
  async getReassessment(_planId: string, reassessId: string): Promise<ApiReassessmentDetail> {
    await delay(200);
    const state = loadState();
    const record = state.reassessments.find((r) => r.id === reassessId);
    if (!record) throw new ApiClientError(4108, '重评记录不存在或不属于该计划', 404);
    return buildReassessmentDetail(state, record);
  },

  /** POST /plans/{plan_id}/reassessments/{reassess_id}/apply：应用调整 */
  async applyReassessment(_planId: string, reassessId: string): Promise<ApiReassessDecision> {
    await delay(250);
    const state = loadState();
    const record = state.reassessments.find((r) => r.id === reassessId);
    if (!record) throw new ApiClientError(4108, '重评记录不存在或不属于该计划', 404);
    if (record.decision !== 'undecided') {
      throw new ApiClientError(3404, '该重评记录已应用或放弃，不可重复操作', 409);
    }
    // 应用：按 plan_adjustment.changes 生效（add task / remove task），done 保持 done
    const added = state.plan.tasks.some((t) => t.name === '完成数据建模专项练习');
    if (!added) {
      state.plan.tasks.push({
        id: `task-new-${Date.now().toString(36)}`,
        name: '完成数据建模专项练习',
        resource: 'sklearn 官方教程 + 公开数据集',
        duration: '1 个月',
        stage: 'short',
        status: 'todo',
        sort_order: state.plan.tasks.length + 1,
        acceptance_criteria: '完成 1 个端到端建模项目并输出评估报告',
      });
    }
    state.plan.tasks = state.plan.tasks.filter((t) => t.id !== 'task-seed-3');
    record.decision = 'applied';
    record.decided_at = nowIso();
    state.plan.progress = recalcProgress(state);
    state.plan.updated_at = nowIso();
    saveState(state);
    return {
      reassess_id: reassessId,
      plan_id: PLAN_ID,
      decision: 'applied',
      applied_at: record.decided_at,
      progress: state.plan.progress,
    };
  },

  /** POST /plans/{plan_id}/reassessments/{reassess_id}/discard：放弃调整 */
  async discardReassessment(_planId: string, reassessId: string): Promise<ApiReassessDecision> {
    await delay(250);
    const state = loadState();
    const record = state.reassessments.find((r) => r.id === reassessId);
    if (!record) throw new ApiClientError(4108, '重评记录不存在或不属于该计划', 404);
    if (record.decision !== 'undecided') {
      throw new ApiClientError(3404, '该重评记录已应用或放弃，不可重复操作', 409);
    }
    record.decision = 'discarded';
    record.decided_at = nowIso();
    saveState(state);
    return { reassess_id: reassessId, plan_id: PLAN_ID, decision: 'discarded', discarded_at: record.decided_at };
  },
};
