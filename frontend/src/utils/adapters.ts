/* ============================================================
   契约 → 展示类型适配器（页面层使用）
   薪资单位：契约 = 元/月；展示组件 = k/月（除以 1000）
   ============================================================ */
import type {
  ApiDirection,
  ApiGapItem,
  ApiMarketJob,
  ApiPlanTask,
  ApiReportListItem,
  CareerDirection,
  MarketJob,
  PlanTask,
  GapItem,
  ReportSummary,
} from '../types';
import { formatDateTime } from './formatDate';

/** 契约方向 → 展示方向卡片（13 字段完整透传，；契约未定义 boxplot/sampleSize，降级近似） */
export function toCareerDirection(d: ApiDirection): CareerDirection {
  const p25 = d.salary?.p25 ?? 0;
  const p50 = d.salary?.p50 ?? 0;
  const p75 = d.salary?.p75 ?? 0;
  const hasSalary = p50 > 0;
  return {
    id: d.id,
    name: d.job_title,
    match: d.match_score,
    salaryMin: hasSalary ? Number((p25 / 1000).toFixed(1)) : 0,
    salaryMax: hasSalary ? Number((p75 / 1000).toFixed(1)) : 0,
    salaryMedian: hasSalary ? Number((p50 / 1000).toFixed(1)) : 0,
    boxplot: hasSalary
      ? { min: Number((p25 / 1000).toFixed(1)), q1: Number((p25 / 1000).toFixed(1)), median: Number((p50 / 1000).toFixed(1)), q3: Number((p75 / 1000).toFixed(1)), max: Number((p75 / 1000).toFixed(1)) }
      : { min: 0, q1: 0, median: 0, q3: 0, max: 0 },
    trend: d.trend === '增长' ? 'growth' : d.trend === '下降' ? 'decline' : 'stable',
    heat: d.heat === '高' ? 'high' : d.heat === '低' ? 'low' : 'medium',
    salaryNote: d.salary_note ?? undefined,
    dataSource: d.data_source ?? undefined,
    recommendReason: d.recommend_reason ?? undefined,
    educationRequirement: d.education_requirement ?? undefined,
    educationMatch: d.education_match ?? undefined,
    competitionNote: d.competition_note ?? undefined,
    certificatesBonus: d.certificates_bonus ?? undefined,
    dataGrade: d.data_grade ?? undefined,
    confidenceReasons: d.confidence_reasons ?? undefined,
    // ：白名单透传 salary_comparison（只透传 level + note，不携带/重算 expected_salary 等原始数字）
    salaryComparison: d.salary_comparison
      ? { level: d.salary_comparison.level, note: d.salary_comparison.note }
      : null,
  };
}

const TREND_CN_TO_EN = { 增长: 'growth', 稳定: 'stable', 下降: 'decline' } as const;
const HEAT_CN_TO_EN = { 高: 'high', 中: 'medium', 低: 'low' } as const;

/** 契约市场岗位 → 展示岗位行（契约无 trendData/heatDist/sampleSize，降级为空） */
export function toMarketJob(job: ApiMarketJob): MarketJob {
  const p25 = job.salary?.p25 ?? 0;
  const p50 = job.salary?.p50 ?? 0;
  const p75 = job.salary?.p75 ?? 0;
  const hasSalary = p50 > 0;
  return {
    id: job.id,
    name: job.job_title,
    city: job.city,
    industry: job.industry,
    salaryMedian: hasSalary ? Number((p50 / 1000).toFixed(1)) : 0,
    heat: HEAT_CN_TO_EN[job.heat as keyof typeof HEAT_CN_TO_EN] ?? 'medium',
    boxplot: hasSalary
      ? { min: Number((p25 / 1000).toFixed(1)), q1: Number((p25 / 1000).toFixed(1)), median: Number((p50 / 1000).toFixed(1)), q3: Number((p75 / 1000).toFixed(1)), max: Number((p75 / 1000).toFixed(1)) }
      : { min: 0, q1: 0, median: 0, q3: 0, max: 0 },
    trendData: [],
    heatDist: [],
    sampleSize: 0,
    salaryNote: undefined,
    dataSource: job.data_source,
    confidence: job.confidence,
  };
}

export const trendLabel = (trend: string | null): CareerDirection['trend'] =>
  TREND_CN_TO_EN[trend as keyof typeof TREND_CN_TO_EN] ?? 'stable';
export const heatLabel = (heat: string | null): CareerDirection['heat'] =>
  HEAT_CN_TO_EN[heat as keyof typeof HEAT_CN_TO_EN] ?? 'medium';

/** 契约计划任务（todo/doing/done）→ 展示任务（pending/doing/done） */
export function toPlanTask(task: ApiPlanTask): PlanTask {
  return {
    id: task.id,
    name: task.name,
    resource: task.resource ?? '',
    duration: task.duration ?? '',
    stage: task.stage,
    status: task.status === 'todo' ? 'pending' : task.status,
    acceptanceCriteria: task.acceptance_criteria ?? undefined,
    coveredByAchievement: task.covered_by_achievement ?? false,
  };
}

/** 契约报告列表项 → 展示报告卡片（stage1 视为画像+方向；stage2 视为含差距+计划） */
export function toReportSummary(item: ApiReportListItem): ReportSummary {
  const types: ReportSummary['types'] =
    item.stage === 'stage2' ? ['portrait', 'directions', 'gap', 'plan'] : ['portrait', 'directions'];
  return {
    id: item.id,
    stage: item.stage,
    status: item.status ?? 'completed',
    date: formatDateTime(item.created_at),
    types,
    score: item.score ?? 0,
    // /：优先 target_job（用户所选方向），缺失时兜底 job_titles[0]
    direction: item.summary.target_job || item.summary.job_titles[0] || undefined,
  };
}

/** 阶段标签：short/mid/long → 中文阶段名 */
export const PHASE_NAME: Record<string, string> = {
  short: '短期（1 个月内）',
  mid: '中期（1-3 个月）',
  long: '长期（3 个月以上）',
};

export const PHASE_DURATION: Record<string, string> = {
  short: '1 个月内',
  mid: '1-3 个月',
  long: '3 个月以上',
};

/** 差距项 level 中文 → 展示 status */
const GAP_LEVEL_TO_STATUS: Record<string, GapItem['status']> = {
  '具备': 'have',
  '部分具备': 'partial',
  '不具备': 'lack',
};

/** 差距项权重数字（0~1）→ 展示枚举（适配规则：≥0.2 high，≥0.1 medium，<0.1 low） */
export function toGapWeight(weight: number): GapItem['weight'] {
  const w = Number(weight);
  if (!Number.isFinite(w)) return 'low';
  if (w >= 0.2) return 'high';
  if (w >= 0.1) return 'medium';
  return 'low';
}

/** 契约差距项 → 展示差距项（：weight=number、level=中文；未知枚举防御兜底，禁止抛错） */
export function toGapItem(item: ApiGapItem): GapItem {
  return {
    skill: item.skill ?? '',
    weight: toGapWeight(item.weight),
    status: GAP_LEVEL_TO_STATUS[item.level] ?? 'partial',
    jdSource: item.jd_source ?? '',
    evidence: item.evidence ?? '',
    dataGrade: item.data_grade ?? undefined,
  };
}
