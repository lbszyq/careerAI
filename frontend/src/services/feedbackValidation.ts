/* ============================================================
   成果 URL 校验（/，T-01 不可信输入约束）
   - 仅接受 http/https 协议 + 长度 ≤500（与后端 3407 双重校验口径一致）
   - 纯函数，无副作用，便于单元测试
   ============================================================ */

export const ACHIEVEMENT_URL_MAX_LENGTH = 500;
export const ACHIEVEMENT_NAME_MAX_LENGTH = 100;
export const ACHIEVEMENT_DESC_MAX_LENGTH = 500;

const HTTP_URL_RE = /^https?:\/\//i;

/** 校验成果 URL：合法返回 null，非法返回用户可见错误文案 */
export function validateAchievementUrl(url: string): string | null {
  const trimmed = url.trim();
  if (!trimmed) return '请填写成果链接';
  if (trimmed.length > ACHIEVEMENT_URL_MAX_LENGTH) return `链接长度不能超过 ${ACHIEVEMENT_URL_MAX_LENGTH} 字符`;
  if (!HTTP_URL_RE.test(trimmed)) return '链接必须以 http:// 或 https:// 开头';
  return null;
}
