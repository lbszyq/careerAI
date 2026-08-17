/* ============================================================
   前端类型定义（阶段二：与 docs/contracts/ 6 文件 21 端点对齐）
   契约类型 = Api* 前缀；展示类型 = 组件 props（阶段一保留）
   ============================================================ */

/* ---------- 通用响应信封（） ---------- */
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T | null;
}

/* ---------- 认证（auth-contract，4 端点） ---------- */
export interface ApiUser {
  id: string;
  username: string;
  phone: string | null;
  role: string;
  created_at: string;
}

export interface ApiTokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface ApiAuthResult {
  user: ApiUser;
  tokens: ApiTokenPair;
}

/* ---------- 画像（profile-contract，3 端点） ---------- */
export interface ApiInternship {
  company: string;
  role: string;
  duration: string;
}

export interface ApiProject {
  name: string;
  description: string;
  tech: string[];
}

export interface ApiProfile {
  id: string;
  name: string | null;
  school: string | null;
  major: string | null;
  education: string | null;
  graduation_year: number | null;
  gpa: number | null;
  skills: string[];
  internships: ApiInternship[];
  projects: ApiProject[];
  certificates: string[];
  preferred_cities: string[];
  preferred_industries: string[];
  expected_salary: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

/** PUT /profile 请求体（部分字段可空，草稿态） */
export interface ApiProfileUpsert {
  name?: string;
  school?: string;
  major?: string;
  education?: string;
  graduation_year?: number;
  gpa?: number;
  skills?: string[];
  internships?: ApiInternship[];
  projects?: ApiProject[];
  certificates?: string[];
  preferred_cities?: string[];
  preferred_industries?: string[];
  expected_salary?: number;
}

/** 简历上传受理结果 */
export interface ApiTaskAccepted {
  task_id: string;
  status: string;
}

/* ---------- 异步任务（tasks-contract，3 端点） ---------- */
export type ApiTaskStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';

export interface ApiTaskJob {
  id: string;
  task_type: string;
  status: ApiTaskStatus;
  progress: number;
  stage: string | null;
  result_ref: string | null;
  result: unknown;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}

/* ---------- 报告（reports-contract，5 端点） ---------- */
export type ApiReportStage = 'stage1' | 'stage2';

/** 报告状态（：列表含生成中记录，前端按此渲染生成中卡片） */
export type ApiReportStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface ApiReportListItem {
  id: string;
  stage: ApiReportStage;
  status: ApiReportStatus;
  score: number | null;
  created_at: string;
  /** ：用户所选目标方向（optional，缺失时前端兜底 job_titles[0]） */
  summary: { job_titles: string[]; target_job?: string };
}

export interface ApiReportList {
  total: number;
  page: number;
  page_size: number;
  items: ApiReportListItem[];
}

/** 置信度原因拆解（v1.1）：supporting=主要依据（+）/ concerns=降低因素（-），挂载画像常模/方向推荐/差距分析 */
export interface ApiConfidenceReasons {
  supporting?: string[];
  concerns?: string[];
}

/** AI 策略建议（v1.1，/）：仅 Stage 2 完整报告返回；全部 optional，缺失时前端不渲染建议卡 */
export interface ApiSuggestion {
  summary?: string | null;
  short_term?: string | null;
  mid_long_term?: string | null;
  reasons?: string[];
  applicable_condition?: string | null;
}

export interface ApiPortraitNorm {
  matched: boolean;
  cohort: string | null;
  band: string | null;
  /** v1.1：样本量（当前 本地版本 约 120），可选 */
  sample_size?: number | null;
  /** v1.1：是否含在职样本，可选 */
  contains_employed?: boolean | null;
  /** v1.1：可靠等级（中等/低等），可选 */
  confidence?: string | null;
  /** v1.1：常模置信度原因拆解，可选 */
  confidence_reasons?: ApiConfidenceReasons | null;
  /** v1.1：免责说明（固定文案），可选 */
  disclaimer?: string | null;
  note: string | null;
}

export interface ApiPortrait {
  overall_score: number;
  dimensions: Record<string, number>;
  norm: ApiPortraitNorm | null;
  strengths: string[];
  weaknesses: string[];
  confidence: string;
}

export interface ApiSalary {
  p25: number | null;
  p50: number | null;
  p75: number | null;
}

/** 期望薪资 vs 岗位薪资分位 level 枚举（/064 契约；半开区间：expected==p50 归 p50_p75） */
export type SalaryLevel = 'below_p25' | 'p25_p50' | 'p50_p75' | 'above_p75' | 'no_data';

/** 契约 salary_comparison：dict | null；null=无期望薪资或 ≤0 */
export interface ApiSalaryComparison {
  expected_salary: number;
  p25: number | null;
  p50: number | null;
  p75: number | null;
  level: SalaryLevel;
  note: string;
}

/** 报告详情内方向推荐（reports-contract） */
export interface ApiDirection {
  id: string;
  job_title: string;
  match_score: number;
  salary: ApiSalary | null;
  salary_note: string | null;
  trend: string | null;
  heat: string | null;
  data_source: string | null;
  education_requirement: string | null;
  education_match: string | null;
  competition_note: string | null;
  certificates_bonus: string | null;
  recommend_reason: string | null;
  /** v1.1：市场数据来源等级（A/B/C），由入库 source_type 派生；可选，缺失时不渲染徽标 */
  data_grade?: string | null;
  /** v1.1：方向推荐置信度原因拆解（supporting/concerns），可选 */
  confidence_reasons?: ApiConfidenceReasons | null;
  /** v1.2：期望薪资 vs 岗位薪资分位对比（契约）；null=无期望薪资/≤0；旧接口缺失 → 前端隐藏 */
  salary_comparison?: ApiSalaryComparison | null;
}

/** 差距项（展示型 GapItem 同构，契约字段对齐） */
export interface ApiGapItem {
  skill: string;
  weight: number; // 0~1，越大越重要（AI 生成）
  level: string; // 具备 / 部分具备 / 不具备
  jd_source: string;
  evidence: string;
  /** v1.1：该 JD 要求对应的市场数据来源等级（A/B/C），可选，缺失时不渲染徽标 */
  data_grade?: string | null;
}

/** 报告详情内嵌差距分析（reports-contract，gap_analysis 结构 已定案） */
export interface ApiGapAnalysis {
  target_job: string;
  match_score?: number | null;
  confidence?: string | null;
  items?: ApiGapItem[];
  note?: string | null;
  /** v1.1：差距分析置信度原因拆解（supporting/concerns），可选 */
  confidence_reasons?: ApiConfidenceReasons | null;
}

/** 报告详情内嵌计划摘要（id 为计划记录引用，后端注入前可为空；后 report.plan 将携带 id） */
export interface ApiPlanSummary {
  id?: string;
  target_job: string;
  stages: Record<string, { label: string; tasks_count: number }>;
  progress: number;
}

export interface ApiReportDetail {
  id: string;
  stage: ApiReportStage;
  status: string;
  portrait: ApiPortrait | null;
  directions: ApiDirection[];
  gap_analysis: ApiGapAnalysis | null;
  plan: ApiPlanSummary | null;
  /** v1.1：AI 策略建议，仅 Stage 2 完整报告返回；可选，缺失时不渲染建议卡 */
  suggestion?: ApiSuggestion | null;
  created_at: string;
  finished_at: string | null;
}

/* ---------- 计划（plans-contract，3 端点） ---------- */
export type ApiPlanTaskStatus = 'todo' | 'doing' | 'done';

export interface ApiPlanTask {
  id: string;
  name: string;
  resource: string | null;
  duration: string | null;
  stage: 'short' | 'mid' | 'long';
  status: ApiPlanTaskStatus;
  sort_order: number;
  /** v1.1：任务验证标准，可选 */
  acceptance_criteria?: string | null;
  /** v1.3：是否已被至少 1 个成果关联覆盖；存量/缺省视为 false */
  covered_by_achievement?: boolean;
}

/** 计划阶段（v1.1）：能力化字段 goal/why/verify/resume_value/stage_completion 全部 optional，存量计划无字段时不渲染 */
export interface ApiPlanStage {
  label: string;
  tasks_count: number;
  /** v1.1：阶段目标能力（JD 要求驱动），可选 */
  goal?: string | null;
  /** v1.1：为什么（对应 JD 要求说明），可选 */
  why?: string | null;
  /** v1.1：项目验证（产出物，覆盖技术/工程/业务三产出），可选 */
  verify?: string | null;
  /** v1.1：简历资产（可写入简历的成果描述），可选 */
  resume_value?: string | null;
  /** v1.1：阶段完成条件（内容定义、不做系统校验），可选 */
  stage_completion?: string | null;
  /** v1.2：阶段完成校验标签 pass/fail/unchecked（取最近一次成功重评的 stage_checks），可选 */
  completion_check?: 'pass' | 'fail' | 'unchecked' | null;
}

/** 最近一次重评任务（plans-contract v1.2 回显，支撑计划页加载态/失败降级/结果入口） */
export interface ApiLatestReassess {
  task_id: string;
  status: ApiTaskStatus;
  /** 成功后重评详情地址（GET /plans/{plan_id}/reassessments/{reassess_id}）；未成功为 null */
  result_ref: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ApiPlanDetail {
  id: string;
  report_id: string;
  gap_analysis_id: string;
  target_job: string;
  stages: Record<'short' | 'mid' | 'long', ApiPlanStage>;
  progress: number;
  tasks: ApiPlanTask[];
  created_at: string;
  updated_at: string;
  /** v1.2：成果列表（空数组=无成果；字段结构见 feedback-contract）；存量计划无字段时成果区隐藏 */
  achievements?: ApiAchievement[];
  /** v1.2：申请重评前置（成果数 ≥1 或存在非 todo 任务）；false 时按钮置灰 */
  reassess_eligible?: boolean;
  /** v1.2：前置不满足时的提示文案（默认「请先上传成果或标记任务进度」） */
  reassess_eligible_reason?: string | null;
  /** v1.2：最近一次重评任务（含进行中/失败，支撑计划页加载态与结果入口）；无记录为 null */
  latest_reassess?: ApiLatestReassess | null;
}

export interface ApiPlanProgress {
  plan_id: string;
  progress: number;
  total_tasks: number;
  done_tasks: number;
  /** v1.3：被成果覆盖的任务数（含已 done，用于展示覆盖规模） */
  covered_tasks?: number;
  /** v1.3：去重后的有效完成数 = |done ∪ covered|（progress 的分子） */
  effective_done_tasks?: number;
  stages: Record<'short' | 'mid' | 'long', { total: number; done: number; covered?: number; effective_done?: number }>;
}

/* ---------- 反馈闭环（feedback-contract v1.2，9 端点） ---------- */

/** 成果记录（成果区列表项） */
export interface ApiAchievement {
  id: string;
  name: string;
  url: string;
  description: string | null;
  /** 关联阶段：short / mid / long */
  stage: 'short' | 'mid' | 'long' | null;
  /** 关联任务 ID */
  task_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ApiAchievementList {
  plan_id: string;
  items: ApiAchievement[];
}

/** 上传/编辑成果请求体（编辑为部分更新，至少 1 个可改字段） */
export interface ApiAchievementUpsert {
  name: string;
  url: string;
  description?: string | null;
  stage?: 'short' | 'mid' | 'long' | null;
  task_id?: string | null;
}

export interface ApiAchievementDeleteResult {
  id: string;
  deleted: boolean;
}

/** POST /plans/{plan_id}/reassessments 受理结果（异步） */
export interface ApiReassessAccepted {
  task_id: string;
  status: string;
}

/** 重评记录决策结果（apply/discard） */
export interface ApiReassessDecision {
  reassess_id: string;
  plan_id: string;
  decision: 'applied' | 'discarded';
  applied_at?: string | null;
  discarded_at?: string | null;
  /** apply 后重算的总体进度 */
  progress?: number;
}

/** 证据引用（重评详情统一结构：type=achievement 含 url；type=task 含 status） */
export interface ApiEvidenceRef {
  type: 'achievement' | 'task';
  id: string;
  name: string;
  url?: string | null;
  status?: string | null;
}

/** ①差距变化 */
export interface ApiGapChange {
  summary: string;
  resolved_items: {
    skill: string;
    evidence_refs: ApiEvidenceRef[];
  }[];
  remaining_items: {
    skill: string;
    level?: string | null;
    confidence?: 'high' | 'medium' | 'low' | null;
    evidence_refs: ApiEvidenceRef[];
  }[];
}

/** ②计划调整（预览：新增/删除/修改 + 冲突点） */
export interface ApiPlanAdjustment {
  summary: string;
  changes: {
    action: 'add' | 'modify' | 'remove';
    target: 'stage' | 'task';
    stage: 'short' | 'mid' | 'long';
    task_id: string | null;
    name: string | null;
    reason: string;
    evidence_refs: ApiEvidenceRef[];
  }[];
  conflicts: {
    task_id: string;
    task_name: string;
    note: string;
  }[];
}

/** ③阶段完成校验（{short,mid,long}.{result,reason,suggestion,stay}） */
export interface ApiStageCheck {
  result: 'pass' | 'fail';
  reason: string;
  suggestion: string | null;
  /** 未通过时 stay=true（停留当前阶段提示，不锁定任务操作） */
  stay: boolean;
}

/** ④调整说明（AI 总结变更原因，必须引用证据） */
export interface ApiAdjustmentExplanation {
  summary: string;
  evidence_refs: ApiEvidenceRef[];
}

/** 重评结果详情（四部分，feedback-contract 数据源） */
export interface ApiReassessmentDetail {
  id: string;
  plan_id: string;
  task_id: string;
  status: string;
  decision: 'undecided' | 'applied' | 'discarded';
  summary: string;
  gap_change: ApiGapChange;
  plan_adjustment: ApiPlanAdjustment;
  stage_checks: Record<'short' | 'mid' | 'long', ApiStageCheck>;
  adjustment_explanation: ApiAdjustmentExplanation;
  created_at: string;
  decided_at: string | null;
}

/* ---------- 市场（market-contract，3 端点） ---------- */
export interface ApiMarketJob {
  id: string;
  job_title: string;
  city: string;
  industry: string;
  salary: ApiSalary | null;
  trend: string | null;
  heat: string | null;
  data_source: string;
  confidence: number;
}

export interface ApiMarketList {
  total: number;
  page: number;
  page_size: number;
  data_quarter: string | null;
  lag_note: string;
  items: ApiMarketJob[];
}

export interface ApiMarketJobDetail extends ApiMarketJob {
  required_skills: string[];
  data_quarter: string;
  updated_at: string;
}

export interface ApiMarketFacets {
  cities: string[];
  industries: string[];
  quarters: string[];
}

/* ============================================================
   展示类型（组件 props，阶段一保留；页面层负责契约→展示适配）
   ============================================================ */

/** 画像五维能力 */
export interface AbilityDimension {
  name: string;
  score: number; // 0-100
  confidence?: 'high' | 'medium' | 'low';
}

/** 能力雷达数据 */
export interface RadarData {
  dimensions: AbilityDimension[];
}

/** 优劣势条目 */
export interface StrengthItem {
  title: string;
  description: string;
  evidence: string;
}

/** 置信度原因拆解（展示；v1.1：supporting=主要依据 + / concerns=降低因素 -） */
export interface ConfidenceReasons {
  supporting?: string[];
  concerns?: string[];
}

/** 期望薪资 vs 岗位薪资分位对比（展示）：组件只消费 level（徽标）+ note（文本），不重复渲染原始数字 */
export interface SalaryComparison {
  level: SalaryLevel;
  note: string;
}

/** 方向推荐卡片（展示） */
export interface CareerDirection {
  id: string;
  name: string;
  match: number; // 匹配度 0-100
  salaryMin: number; // k/月
  salaryMax: number;
  salaryMedian: number;
  boxplot: { min: number; q1: number; median: number; q3: number; max: number };
  trend: 'growth' | 'stable' | 'decline';
  heat: 'high' | 'medium' | 'low';
  salaryNote?: string;
  dataSource?: string;
  /** 推荐理由（：面向用户、≤40 字） */
  recommendReason?: string;
  /** 学历门槛与匹配度；竞争度 / 证书加分同理 */
  educationRequirement?: string;
  educationMatch?: string;
  competitionNote?: string;
  certificatesBonus?: string;
  /** v1.1：市场数据来源等级（A/B/C），缺失时不渲染徽标 */
  dataGrade?: string;
  /** v1.1：方向推荐置信度原因拆解 */
  confidenceReasons?: ConfidenceReasons;
  /** v1.2：期望薪资 vs 岗位薪资分位对比；null/缺失 → 隐藏对比行 */
  salaryComparison?: SalaryComparison | null;
}

/** 差距项（展示） */
export interface GapItem {
  skill: string;
  weight: 'high' | 'medium' | 'low';
  status: 'have' | 'partial' | 'lack';
  /** 对应 JD 要求（追溯来源） */
  jdSource: string;
  /** 判定依据（用户侧证据） */
  evidence: string;
  /** v1.1：该 JD 要求对应的市场数据来源等级（A/B/C），缺失时不渲染徽标 */
  dataGrade?: string;
}

/** 计划任务（展示；status 用 pending/doing/done，页面层从 todo 适配） */
export interface PlanTask {
  id: string;
  name: string;
  resource: string;
  duration: string;
  stage: 'short' | 'mid' | 'long';
  status: 'pending' | 'doing' | 'done';
  /** v1.1：任务验证标准，可选 */
  acceptanceCriteria?: string;
  /** v1.3：是否已被至少 1 个成果关联覆盖；存量/缺省视为 false */
  coveredByAchievement?: boolean;
}

/** 计划阶段（展示） */
export interface PlanPhase {
  id: string;
  name: string;
  duration: string;
  tasks: PlanTask[];
}

/** 市场岗位行（展示） */
export interface MarketJob {
  id: string;
  name: string;
  city: string;
  industry: string;
  salaryMedian: number; // k/月
  heat: 'high' | 'medium' | 'low';
  boxplot: { min: number; q1: number; median: number; q3: number; max: number };
  trendData: { month: string; demand: number }[];
  heatDist: { level: string; count: number }[];
  sampleSize: number;
  salaryNote?: string;
  dataSource?: string;
  confidence?: number;
}

/** 历史报告卡片（展示） */
export interface ReportSummary {
  id: string;
  stage: ApiReportStage;
  status: ApiReportStatus;
  date: string;
  types: ('portrait' | 'directions' | 'gap' | 'plan')[];
  score: number;
  direction?: string;
}

/** 生成阶段 */
export type GeneratingStage = 1 | 2;

/** 用户信息（会话态草稿，阶段一保留） */
export interface UserProfile {
  name?: string;
  school?: string;
  major?: string;
  degree?: string;
  gradYear?: string;
  skills: string[];
  cities: string[];
  industries: string[];
  salaryRange?: string;
}
