/* ============================================================
   plans API（plans-contract v1.2 + feedback-contract v1.2，9 端点）
   - 计划详情 / 进度 / 任务状态（既有）
   - 成果 CRUD 与重评端点（：反馈闭环）
   ============================================================ */
import { request } from './http';
import type {
  ApiAchievement,
  ApiAchievementDeleteResult,
  ApiAchievementList,
  ApiAchievementUpsert,
  ApiPlanDetail,
  ApiPlanProgress,
  ApiPlanTaskStatus,
  ApiReassessAccepted,
  ApiReassessDecision,
  ApiReassessmentDetail,
} from '../types';

export interface PlanTaskStatusResult {
  plan_id: string;
  task_id: string;
  task_status: ApiPlanTaskStatus;
  progress: number;
}

export const plansApi = {
  /** GET /plans/{plan_id}：成长计划详情（v1.2 含成果/重评回显字段） */
  detail(planId: string): Promise<ApiPlanDetail> {
    return request<ApiPlanDetail>(`/plans/${planId}`);
  },
  /** GET /plans/{plan_id}/progress：计划进度 */
  progress(planId: string): Promise<ApiPlanProgress> {
    return request<ApiPlanProgress>(`/plans/${planId}/progress`);
  },
  /** PATCH /plans/{plan_id}/tasks/{task_id}：更新任务状态（幂等） */
  updateTaskStatus(planId: string, taskId: string, status: ApiPlanTaskStatus): Promise<PlanTaskStatusResult> {
    return request<PlanTaskStatusResult>(`/plans/${planId}/tasks/${taskId}`, {
      method: 'PATCH',
      body: { status },
    });
  },
  /** GET /plans/{plan_id}/achievements：成果列表（按创建时间倒序） */
  listAchievements(planId: string): Promise<ApiAchievementList> {
    return request<ApiAchievementList>(`/plans/${planId}/achievements`);
  },
  /** POST /plans/{plan_id}/achievements：上传成果（名称必填 + URL 必填，URL 双重校验） */
  createAchievement(planId: string, payload: ApiAchievementUpsert): Promise<ApiAchievement> {
    return request<ApiAchievement>(`/plans/${planId}/achievements`, { method: 'POST', body: payload });
  },
  /** PATCH /plans/{plan_id}/achievements/{achievement_id}：编辑成果（部分更新；传 null 解除关联） */
  updateAchievement(planId: string, achievementId: string, payload: Partial<ApiAchievementUpsert>): Promise<ApiAchievement> {
    return request<ApiAchievement>(`/plans/${planId}/achievements/${achievementId}`, { method: 'PATCH', body: payload });
  },
  /** DELETE /plans/{plan_id}/achievements/{achievement_id}：删除成果（用户可删自己的成果） */
  deleteAchievement(planId: string, achievementId: string): Promise<ApiAchievementDeleteResult> {
    return request<ApiAchievementDeleteResult>(`/plans/${planId}/achievements/${achievementId}`, { method: 'DELETE' });
  },
  /** POST /plans/{plan_id}/reassessments：申请重新评估（异步受理，返回 task_id 轮询） */
  requestReassessment(planId: string): Promise<ApiReassessAccepted> {
    return request<ApiReassessAccepted>(`/plans/${planId}/reassessments`, { method: 'POST' });
  },
  /** GET /plans/{plan_id}/reassessments/{reassess_id}：重评结果详情（四部分） */
  getReassessment(planId: string, reassessId: string): Promise<ApiReassessmentDetail> {
    return request<ApiReassessmentDetail>(`/plans/${planId}/reassessments/${reassessId}`);
  },
  /** POST /plans/{plan_id}/reassessments/{reassess_id}/apply：应用调整（保留已完成标记，决策幂等 3404） */
  applyReassessment(planId: string, reassessId: string): Promise<ApiReassessDecision> {
    return request<ApiReassessDecision>(`/plans/${planId}/reassessments/${reassessId}/apply`, { method: 'POST' });
  },
  /** POST /plans/{plan_id}/reassessments/{reassess_id}/discard：放弃调整（原计划不变，决策幂等 3404） */
  discardReassessment(planId: string, reassessId: string): Promise<ApiReassessDecision> {
    return request<ApiReassessDecision>(`/plans/${planId}/reassessments/${reassessId}/discard`, { method: 'POST' });
  },
};
