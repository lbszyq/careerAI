/* ============================================================
   reports API（reports-contract，5 端点）
   ============================================================ */
import { request } from './http';
import type { ApiReportDetail, ApiReportList, ApiTaskAccepted } from '../types';

export interface CreateReportPayload {
  profile_id: string;
  preferred_cities?: string[];
  preferred_industries?: string[];
}

export const reportsApi = {
  /** POST /reports：提交 Stage 1（画像+方向），返回 task_id */
  create(payload: CreateReportPayload): Promise<ApiTaskAccepted> {
    return request<ApiTaskAccepted>('/reports', { method: 'POST', body: payload });
  },
  /** GET /reports：我的报告列表（分页） */
  list(page = 1, pageSize = 10): Promise<ApiReportList> {
    return request<ApiReportList>(`/reports?page=${page}&page_size=${pageSize}`);
  },
  /** GET /reports/{report_id}：报告详情 */
  detail(reportId: string): Promise<ApiReportDetail> {
    return request<ApiReportDetail>(`/reports/${reportId}`);
  },
  /** POST /reports/{report_id}/gap：提交 Stage 2（差距+计划），返回 task_id */
  createGap(reportId: string, directionId: string): Promise<ApiTaskAccepted> {
    return request<ApiTaskAccepted>(`/reports/${reportId}/gap`, {
      method: 'POST',
      body: { direction_id: directionId },
    });
  },
  /** POST /reports/{report_id}/plan：重新生成成长计划，返回 task_id */
  regeneratePlan(reportId: string): Promise<ApiTaskAccepted> {
    return request<ApiTaskAccepted>(`/reports/${reportId}/plan`, { method: 'POST' });
  },
};
