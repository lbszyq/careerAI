/* ============================================================
   profile API（profile-contract，3 端点）
   ============================================================ */
import { request, uploadFile } from './http';
import type { ApiProfile, ApiProfileUpsert, ApiTaskAccepted } from '../types';

export const profileApi = {
  /** POST /profile/resume：上传简历触发异步解析（PDF/PNG/JPG ≤10MB） */
  uploadResume(file: File): Promise<ApiTaskAccepted> {
    const formData = new FormData();
    formData.append('file', file);
    return uploadFile<ApiTaskAccepted>('/profile/resume', formData);
  },
  /** GET /profile：当前活跃画像（未填写返回 null） */
  get(): Promise<ApiProfile | null> {
    return request<ApiProfile | null>('/profile');
  },
  /** PUT /profile：手动表单保存/补填（upsert，允许草稿） */
  upsert(payload: ApiProfileUpsert): Promise<ApiProfile> {
    return request<ApiProfile>('/profile', { method: 'PUT', body: payload });
  },
};
