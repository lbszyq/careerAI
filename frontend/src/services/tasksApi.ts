/* ============================================================
   tasks API（tasks-contract，3 端点）
   ============================================================ */
import { request } from './http';
import type { ApiTaskAccepted, ApiTaskJob } from '../types';

export interface TriggerTaskPayload {
  task_type: string;
  params?: Record<string, unknown>;
}

export const tasksApi = {
  /** POST /tasks/trigger：通用任务触发（开发/调试用） */
  trigger(payload: TriggerTaskPayload): Promise<ApiTaskAccepted> {
    return request<ApiTaskAccepted>('/tasks/trigger', { method: 'POST', body: payload });
  },
  /** GET /tasks/{task_id}：任务状态轮询（前端 5s） */
  get(taskId: string): Promise<ApiTaskJob> {
    return request<ApiTaskJob>(`/tasks/${taskId}`);
  },
  /** POST /tasks/{task_id}/cancel：取消进行中任务（终态后不可取消 3003） */
  cancel(taskId: string): Promise<ApiTaskAccepted> {
    return request<ApiTaskAccepted>(`/tasks/${taskId}/cancel`, { method: 'POST' });
  },
};
