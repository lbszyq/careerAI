import { describe, expect, it } from 'vitest';

import { formatDateTime } from './formatDate';

describe('formatDateTime 日期时间格式化', () => {
  it('合法 ISO 时间格式化为 YYYY-MM-DD HH:mm', () => {
    expect(formatDateTime('2026-08-09T10:30:00')).toBe('2026-08-09 10:30');
  });

  it('空值（undefined/null）返回占位符 —', () => {
    expect(formatDateTime(undefined)).toBe('—');
    expect(formatDateTime(null)).toBe('—');
  });

  it('非法输入返回占位符 —（边界）', () => {
    expect(formatDateTime('not-a-date')).toBe('—');
    expect(formatDateTime('')).toBe('—');
  });
});
