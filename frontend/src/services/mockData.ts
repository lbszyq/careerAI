/* ============================================================
   Mock 数据（阶段一原型专用；阶段二降级为 fallback/选项数据）
   - 页面数据源已切换到真实 API
   - 保留：表单选项（城市/行业/学历/毕业年份/薪资范围/技能）+ 生成中提示文案
   - 移除：mockProfile/mockRadar/mockDirections/mockPlan/mockReports/marketJobs 等数据型导出
     （原导出由页面引用处已替换为真实 API 适配；删除前先确认无引用）
   ============================================================ */
import type { ApiDirection } from '../types';

/** 城市 / 行业 / 学历选项（表单与筛选共用） */
export const cityOptions = ['北京', '上海', '广州', '深圳', '杭州', '成都', '武汉', '南京'];
export const industryOptions = ['互联网', '金融', '快消', '咨询', '制造业', '新能源', '教育'];
/** 学历枚举与契约对齐（profile-contract：专科/本科/硕士/博士） */
export const degreeOptions = ['专科', '本科', '硕士', '博士'];
export const gradYearOptions = ['2024', '2025', '2026', '2027', '2028'];
export const salaryRangeOptions = ['8-12k', '12-18k', '18-25k', '25k+'];
export const skillOptions = ['Python', 'SQL', 'Excel', '数据分析', '数据可视化', '机器学习', 'Java', 'JavaScript', '产品设计', '用户研究', '沟通表达', '项目管理', 'SPSS', 'Tableau', 'Power BI'];

/** 生成中提示语轮播 */
export const generatingTips = [
  '报告基于你填写的资料与公开市场信息生成，样本量会如实标注',
  '市场数据来自公开信息聚合，样本量会标注',
  '补充实习与项目经历，可显著提升报告精准度',
];

/** 生成步骤文案（stage=1 画像 / stage=2 差距计划） */
export const generatingSteps: Record<1 | 2, string[]> = {
  1: ['简历解析', '画像分析', '市场检索', '报告整合'],
  2: ['岗位要求提取', '差距计算', '计划生成'],
};

export const generatingTitles: Record<1 | 2, string> = {
  1: '正在为你生成职业画像',
  2: '正在生成差距分析与成长计划',
};

/* ：方向薪资对比 mock 样例——覆盖 salary_comparison 6 态
   （below_p25 / p25_p50 / p50_p75 / above_p75 + null + no_data）
   供页面演示 / 测试（经 toCareerDirection 适配后进入 SalaryComparison 组件） */
const baseMockDirection = {
  job_title: '',
  match_score: 90,
  salary: { p25: 8000, p50: 12000, p75: 18000 },
  salary_note: null,
  trend: '增长',
  heat: '高',
  data_source: '公开样本（演示）',
  education_requirement: '本科',
  education_match: '匹配',
  competition_note: null,
  certificates_bonus: null,
  recommend_reason: '演示方向',
} satisfies Omit<ApiDirection, 'id'>;

export const mockSalaryComparisonDirections: ApiDirection[] = [
  {
    ...baseMockDirection,
    id: 'mock-salary-below-p25',
    job_title: '演示岗位·低于 25 分位',
    salary_comparison: { expected_salary: 6000, p25: 8000, p50: 12000, p75: 18000, level: 'below_p25', note: '你的期望薪资 6k/月 低于该岗位市场 25 分位。' },
  },
  {
    ...baseMockDirection,
    id: 'mock-salary-p25-p50',
    job_title: '演示岗位·25-50 分位',
    salary_comparison: { expected_salary: 10000, p25: 8000, p50: 12000, p75: 18000, level: 'p25_p50', note: '你的期望薪资 10k/月 处于该岗位市场 25-50 分位段。' },
  },
  {
    ...baseMockDirection,
    id: 'mock-salary-p50-p75',
    job_title: '演示岗位·50-75 分位',
    salary_comparison: { expected_salary: 12000, p25: 8000, p50: 12000, p75: 18000, level: 'p50_p75', note: '你的期望薪资 12k/月 处于该岗位薪资区间 50-75 分位段（8k-18k），与市场 50 分位持平。' },
  },
  {
    ...baseMockDirection,
    id: 'mock-salary-above-p75',
    job_title: '演示岗位·高于 75 分位',
    salary_comparison: { expected_salary: 20000, p25: 8000, p50: 12000, p75: 18000, level: 'above_p75', note: '你的期望薪资 20k/月 高于该岗位市场 75 分位。' },
  },
  {
    ...baseMockDirection,
    id: 'mock-salary-null',
    job_title: '演示岗位·无期望薪资',
    salary_comparison: null,
  },
  {
    ...baseMockDirection,
    id: 'mock-salary-no-data',
    job_title: '演示岗位·无薪资数据',
    salary_comparison: { expected_salary: 12000, p25: null, p50: null, p75: null, level: 'no_data', note: '暂无该岗位薪资数据' },
  },
];
