/* ============================================================
   错误码 → 用户可见 UI 映射（§Error UX Mapping）
   集中管理，组件内禁止散落 switch-case
   ============================================================ */

export interface ApiErrorLike {
  code: number;
  message: string;
  httpStatus: number;
}

/** 认证/授权类（1xxx） */
const AUTH_CODES = new Set([1001, 1002, 1003]);

/** 参数校验类（2xxx） */
const PARAM_CODES = new Set([2001, 2002]);

/** 业务规则类（3xxx） */
const BUSINESS_CODES = new Set([3001, 3002, 3003, 3101, 3103, 3104, 3201, 3202, 3203, 3204, 3205, 3301, 3401, 3402, 3403, 3404, 3405, 3406, 3407]);

/** 资源类（4xxx） */
const RESOURCE_CODES = new Set([4001, 4101, 4102, 4103, 4104, 4106, 4107, 4108, 4109]);

/** 外部依赖类（5xxx） */
const EXTERNAL_CODES = new Set([5102]);

/** 系统/未实现（6xxx） */
const SYSTEM_CODES = new Set([6001]);

/** 契约中的命名错误码（用户友好文案），未命中时用后端 message */
const NAMED_MESSAGES: Record<number, string> = {
  1001: '登录状态已失效，请重新登录',
  1002: '无权访问该资源',
  1003: '登录已过期，请重新登录',
  2001: '提交的信息格式有误，请检查后重试',
  3001: '该用户名或资源已存在',
  3002: '该手机号已注册',
  3003: '任务已结束，无法取消',
  3101: '画像数量已达上限',
  3103: '仅支持 PDF 文字版简历（图片/扫描件暂不支持解析，OCR 后续版本支持），可手动填写下方表单',
  3104: '文件超过 10MB：请压缩为 PDF 后重试（勿转成图片，图片版无法解析）；或直接手动填写下方表单',
  3201: '已有进行中的分析任务，请稍候',
  3202: '今日报告生成次数已达上限，请明天再试',
  3203: '用户画像信息不完整，请补充后重试',
  3204: '请先选择目标方向',
  3205: '该报告尚未完成差距分析，无法重新生成计划',
  3301: '任务状态不合法',
  3401: '筛选参数不合法',
  3402: '请先上传成果或标记任务进度',
  3403: '该计划已有进行中的重评任务，请稍候',
  3404: '该重评记录已应用或放弃，不可重复操作',
  3405: '该重评记录暂不可操作，请刷新后重试',
  3406: '关联任务不属于该计划',
  3407: '链接仅支持 http/https 且不超过 500 字符',
  4001: '任务不存在或已被清理',
  4101: '画像不存在',
  4102: '报告不存在',
  4103: '目标方向不存在',
  4104: '成长计划不存在',
  4106: '计划任务不存在',
  4107: '岗位记录不存在',
  4108: '重评记录不存在',
  4109: '成果不存在或不属于该计划',
  5102: 'AI 服务暂时不可用，请稍后重试',
  6001: '系统繁忙，请稍后再试',
};

/** 映射为表单字段错误提示（仅参数校验类） */
export function toFieldError(code: number): string | null {
  if (PARAM_CODES.has(code)) return NAMED_MESSAGES[code] ?? '请检查输入内容';
  return null;
}

/** 判断是否需要跳转登录 */
export function isUnauthorized(code: number): boolean {
  return code === 1001 || code === 1003;
}

/** 判断是否需要尝试 token 刷新（1001 也可能是业务未登录；1003 token 过期明确可刷） */
export function isRefreshable(code: number): boolean {
  return code === 1003;
}

/** 错误码 → 用户可见文案（组件/Toast 使用） */
export function toUserMessage(error: ApiErrorLike): string {
  if (AUTH_CODES.has(error.code)) return NAMED_MESSAGES[error.code] ?? error.message;
  if (PARAM_CODES.has(error.code)) return NAMED_MESSAGES[error.code] ?? error.message;
  if (BUSINESS_CODES.has(error.code)) return NAMED_MESSAGES[error.code] ?? error.message;
  if (RESOURCE_CODES.has(error.code)) return NAMED_MESSAGES[error.code] ?? error.message;
  if (EXTERNAL_CODES.has(error.code)) return NAMED_MESSAGES[error.code] ?? error.message;
  if (SYSTEM_CODES.has(error.code)) return NAMED_MESSAGES[error.code] ?? error.message;
  // 未知错误码：兜底不暴露内部细节
  return '操作失败，请稍后再试';
}

/** 错误类型分类（用于表单内联 vs Toast vs ErrorState） */
export type ErrorCategory = 'field' | 'auth' | 'toast' | 'page';

export function categorizeError(code: number): ErrorCategory {
  if (PARAM_CODES.has(code)) return 'field';
  if (AUTH_CODES.has(code)) return 'auth';
  if (SYSTEM_CODES.has(code)) return 'page';
  return 'toast';
}
