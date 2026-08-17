/* Page-01 首页 / 仪表盘
   未登录首访：Hero（40px 标题 + 价值点 3 行「左文右数，非三等分卡片」）+「开始我的职业分析」
   已登录：欢迎语 + 画像摘要卡（左 7 右 5）+ 方向快捷入口 + 市场提示
   阶段二：画像/计划/方向来自真实 API（GET /reports + GET /plans）；后端未就绪时降级为引导态 */
import { useEffect, useState } from 'react';
import { Button, Card, Alert, Row, Col, Divider, Skeleton } from 'antd';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../stores/useAuthStore';
import PortraitSummaryCard from '../components/business/PortraitSummaryCard';
import ProgressRing from '../components/ui/ProgressRing';
import DirectionCard from '../components/business/DirectionCard';
import DataNote from '../components/ui/DataNote';
import { reportsApi } from '../services/reportsApi';
import { plansApi } from '../services/plansApi';
import { toCareerDirection } from '../utils/adapters';
import { formatDateTime } from '../utils/formatDate';
import type { ApiPlanDetail, ApiReportDetail, RadarData } from '../types';

const LAST_PLAN_KEY = 'careerai:last_plan_id';

const DIMENSION_NAMES: Record<string, string> = {
  technical: '技术能力',
  project: '项目经验',
  academic: '学术背景',
  soft_skill: '软技能',
  industry_knowledge: '行业认知',
};

/** 价值点（PRD 事实数据，非 mock 数字） */
const VALUE_POINTS = [
  { title: '职业竞争力评估', value: '0-100 分', desc: '五维能力与常模对比' },
  { title: '职业方向推荐', value: '3-5 个', desc: '匹配度 / 薪资 / 趋势透明对比' },
  { title: '差距驱动成长计划', value: '三阶段', desc: '任务 / 资源 / 耗时可执行' },
];

export default function HomePage() {
  const navigate = useNavigate();
  const { isLoggedIn, user } = useAuth();

  const [report, setReport] = useState<ApiReportDetail | null>(null);
  const [plan, setPlan] = useState<ApiPlanDetail | null>(null);
  const [dashLoading, setDashLoading] = useState(true);

  useEffect(() => {
    if (!isLoggedIn) {
      setDashLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      let detail: ApiReportDetail | null = null;
      try {
        const list = await reportsApi.list(1, 1);
        if (cancelled) return;
        if (list.items.length > 0) {
          detail = await reportsApi.detail(list.items[0].id);
          if (!cancelled) setReport(detail);
        }
      } catch {
        /* 后端未就绪：降级为引导态 */
      }
      try {
        // ：优先最近报告关联计划（detail.plan.id），其次 sessionStorage 旧标记（兼容旧行为）
        const planId = detail?.plan?.id ?? sessionStorage.getItem(LAST_PLAN_KEY);
        if (planId) {
          const planDetail = await plansApi.detail(planId);
          if (!cancelled) setPlan(planDetail);
        }
      } catch {
        /* 忽略计划加载失败 */
      } finally {
        if (!cancelled) setDashLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isLoggedIn]);

  const startAnalysis = () => {
    navigate('/profile');
  };

  /* 未登录首次态 */
  if (!isLoggedIn) {
    return (
      <div className="container-max page-body">
        {/* Hero：唯一允许 40px 标题（design-system） */}
        <div style={{ textAlign: 'center', padding: 'var(--space-12) 0 var(--space-12)' }}>
          <h1 style={{ fontSize: 'var(--font-size-4xl)', fontWeight: 700, lineHeight: 1.25, margin: 0 }}>
            AI 帮你做出
            <br />
            更好的职业决策
          </h1>
          <p
            style={{
              margin: 'var(--space-4) auto 0',
              maxWidth: 560,
              fontSize: 'var(--font-size-lg)',
              lineHeight: '27px',
              color: 'var(--color-text-secondary)',
            }}
          >
            面向应届毕业生：职业画像 → 方向推荐 → 差距分析 → 成长计划，一站式职业规划
          </p>
          <Button type="primary" size="large" style={{ marginTop: 'var(--space-8)', minHeight: 48, padding: '0 36px', fontSize: 'var(--font-size-base)' }} onClick={startAnalysis}>
            开始我的职业分析
          </Button>
        </div>

        {/* 价值点 3 行：左文右数，非卡片，divider 分隔（设计规范 page-01） */}
        <div style={{ maxWidth: 720, margin: '0 auto', borderTop: '1px solid var(--color-divider)' }}>
          {VALUE_POINTS.map((point, index) => (
            <div key={point.title}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 'var(--space-8)',
                  padding: 'var(--space-8) 0',
                }}
              >
                <div>
                  <div style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>{point.title}</div>
                  <div style={{ marginTop: 4, fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>{point.desc}</div>
                </div>
                <div className="tnum" style={{ fontSize: 'var(--font-size-3xl)', fontWeight: 700, color: 'var(--color-accent-500)', whiteSpace: 'nowrap' }}>
                  {point.value}
                </div>
              </div>
              {index < VALUE_POINTS.length - 1 && <Divider style={{ margin: 0, borderColor: 'var(--color-divider)' }} />}
            </div>
          ))}
        </div>
      </div>
    );
  }

  /* 已登录：仪表盘态 */
  const portrait = report?.portrait;
  // ：portrait.dimensions 为空/缺失时 radar 置 null，走「还没有职业画像」兜底（禁止空指标进雷达图）
  const dimensionEntries = Object.entries(portrait?.dimensions ?? {});
  const radar: RadarData | null =
    portrait && dimensionEntries.length > 0
      ? {
          dimensions: dimensionEntries.map(([key, score]) => ({
            name: DIMENSION_NAMES[key] ?? key,
            score: Number(score),
          })),
        }
      : null;
  const directions = (report?.directions ?? []).map(toCareerDirection);

  return (
    <div className="container-max page-body">
      {/* 顶部欢迎语 */}
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 600 }}>
          你好，{user?.username ?? '同学'}，欢迎回来
        </div>
        <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
          {report ? `最近报告生成于 ${formatDateTime(report.created_at)}` : '完成一次职业分析后，你的数据会显示在这里'}
        </div>
      </div>

      {dashLoading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : (
        <Row gutter={24}>
          {/* 中部：左 7 画像摘要 / 右 5 计划进度 */}
          <Col xs={24} lg={14} style={{ marginBottom: 'var(--space-6)' }}>
            {portrait && radar ? (
              <PortraitSummaryCard
                score={portrait.overall_score}
                percentileText={portrait.norm?.band ? `处于参考样本${portrait.norm.band}` : undefined}
                scoreNote={portrait.norm?.note ?? undefined}
                radar={radar}
                date={formatDateTime(report?.created_at)}
                reportId={report?.id}
              />
            ) : (
              <Card style={{ borderRadius: 'var(--radius-md)', height: '100%' }} styles={{ body: { padding: 'var(--space-8)', textAlign: 'center' } }}>
                <div style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>还没有职业画像</div>
                <div style={{ marginTop: 4, fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
                  完成一次职业分析后，画像摘要会显示在这里
                </div>
                <Button type="primary" style={{ marginTop: 'var(--space-4)' }} onClick={startAnalysis}>
                  开始职业分析
                </Button>
              </Card>
            )}
          </Col>
          <Col xs={24} lg={10} style={{ marginBottom: 'var(--space-6)' }}>
            {/* ：内容垂直居中（body flex column + center），消除与画像卡等高后的底部大片留白；不恢复任务明细 */}
            <Card
              style={{ borderRadius: 'var(--radius-md)', height: '100%' }}
              styles={{ body: { padding: 'var(--space-6)', display: 'flex', flexDirection: 'column', justifyContent: 'center', height: '100%' } }}
            >
              {plan ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-6)' }}>
                  <ProgressRing percent={plan.progress} size={120} />
                  <div>
                    <div style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>成长计划</div>
                    <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
                      已完成 {plan.tasks.filter((t) => t.status === 'done').length}/{plan.tasks.length} 项任务
                    </div>
                    <Button type="link" style={{ padding: 0 }} onClick={() => navigate(`/my-plan?planId=${plan.id}`)}>
                      查看我的计划
                    </Button>
                  </div>
                </div>
              ) : (
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>暂无成长计划</div>
                  <div style={{ marginTop: 4, fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
                    生成差距分析后，成长计划会复制到这里执行
                  </div>
                  <Button type="primary" style={{ marginTop: 'var(--space-4)' }} onClick={startAnalysis}>
                    开始职业分析
                  </Button>
                </div>
              )}
            </Card>
          </Col>
        </Row>
      )}

      {/* 底部：左 7 推荐方向入口 / 右 5 市场提示 */}
      <Row gutter={24}>
        <Col xs={24} lg={14} style={{ marginBottom: 'var(--space-6)' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 'var(--space-4)' }}>
            <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600, margin: 0 }}>推荐其他方向</h2>
            {report && (
              <Button type="link" onClick={() => navigate(`/report/directions?reportId=${report.id}`)}>
                重新选择
              </Button>
            )}
          </div>
          {directions.length > 0 ? (
            <Row gutter={24}>
              {directions.slice(0, 2).map((d) => (
                <Col xs={24} md={12} key={d.id} style={{ marginBottom: 'var(--space-4)' }}>
                  <DirectionCard direction={d} readOnly />
                </Col>
              ))}
            </Row>
          ) : (
            <Card style={{ borderRadius: 'var(--radius-md)' }} styles={{ body: { padding: 'var(--space-6)', textAlign: 'center' } }}>
              <DataNote>完成职业分析后，推荐其他方向会显示在这里</DataNote>
            </Card>
          )}
        </Col>
        <Col xs={24} lg={10}>
          <Alert
            type="info"
            showIcon
            message="市场数据已更新"
            description={
              <span>
                基于季度公开数据聚合（人社部 / 劳科院 / 智联季度报告，B-001 定案）
                <DataNote>数据更新周期：季度 + 年度补充；滞后约 1-1.5 个月</DataNote>
              </span>
            }
            style={{ borderRadius: 'var(--radius-md)' }}
          />
        </Col>
      </Row>
    </div>
  );
}
