/* 日期时间格式化工具（/Q7：报告时间统一精确到小时 YYYY-MM-DD HH:mm） */
import dayjs from 'dayjs';

/** ISO 时间字符串 → YYYY-MM-DD HH:mm；空值/非法输入返回占位符 '—' */
export function formatDateTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = dayjs(iso);
  return d.isValid() ? d.format('YYYY-MM-DD HH:mm') : '—';
}
