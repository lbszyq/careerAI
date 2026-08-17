/* ============================================================
   反馈闭环 API 门面
   - VITE_FEEDBACK_MOCK=true → 契约 mock（后端未合入时联调/演示）
   - 默认 false → 真实 API（plansApi 反馈方法 + tasksApi.get）
   - 统一接口供 MyPlanPage 使用，切换零代码改动
   ============================================================ */
import { plansApi } from './plansApi';
import { tasksApi } from './tasksApi';
import { feedbackMock } from './feedbackMock';
import type {
  ApiAchievement,
  ApiAchievementDeleteResult,
  ApiAchievementList,
  ApiAchievementUpsert,
  ApiPlanDetail,
  ApiPlanTaskStatus,
  ApiReassessAccepted,
  ApiReassessDecision,
  ApiReassessmentDetail,
  ApiTaskJob,
} from '../types';
import type { PlanTaskStatusResult } from './plansApi';

/** 反馈闭环统一接口（页面层只依赖本门面） */
export interface FeedbackApi {
  getPlan(planId: string): Promise<ApiPlanDetail>;
  updateTaskStatus(planId: string, taskId: string, status: ApiPlanTaskStatus): Promise<PlanTaskStatusResult>;
  listAchievements(planId: string): Promise<ApiAchievementList>;
  createAchievement(planId: string, payload: ApiAchievementUpsert): Promise<ApiAchievement>;
  updateAchievement(planId: string, achievementId: string, payload: Partial<ApiAchievementUpsert>): Promise<ApiAchievement>;
  deleteAchievement(planId: string, achievementId: string): Promise<ApiAchievementDeleteResult>;
  requestReassessment(planId: string): Promise<ApiReassessAccepted>;
  getTask(taskId: string): Promise<ApiTaskJob>;
  getReassessment(planId: string, reassessId: string): Promise<ApiReassessmentDetail>;
  applyReassessment(planId: string, reassessId: string): Promise<ApiReassessDecision>;
  discardReassessment(planId: string, reassessId: string): Promise<ApiReassessDecision>;
}

const realFeedbackApi: FeedbackApi = {
  getPlan: (planId) => plansApi.detail(planId),
  updateTaskStatus: (planId, taskId, status) => plansApi.updateTaskStatus(planId, taskId, status),
  listAchievements: (planId) => plansApi.listAchievements(planId),
  createAchievement: (planId, payload) => plansApi.createAchievement(planId, payload),
  updateAchievement: (planId, achievementId, payload) => plansApi.updateAchievement(planId, achievementId, payload),
  deleteAchievement: (planId, achievementId) => plansApi.deleteAchievement(planId, achievementId),
  requestReassessment: (planId) => plansApi.requestReassessment(planId),
  getTask: (taskId) => tasksApi.get(taskId),
  getReassessment: (planId, reassessId) => plansApi.getReassessment(planId, reassessId),
  applyReassessment: (planId, reassessId) => plansApi.applyReassessment(planId, reassessId),
  discardReassessment: (planId, reassessId) => plansApi.discardReassessment(planId, reassessId),
};

/** 后端未合入时切契约 mock；后端合入后设 false 即真实 API */
export const USE_FEEDBACK_MOCK = import.meta.env.VITE_FEEDBACK_MOCK === 'true';

export const feedbackApi: FeedbackApi = USE_FEEDBACK_MOCK ? feedbackMock : realFeedbackApi;
