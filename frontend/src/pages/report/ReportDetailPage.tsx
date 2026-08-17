/* Page-07 完整报告聚合页（用户决策方案 C：一页看全）
   顺序：画像摘要 → 方向推荐 → 目标岗位与差距分析 → 成长计划
   数据：reportsApi.detail 一次拉全（portrait/directions/gap_analysis/plan）；
        plan 任务明细经 report.plan?.id → plansApi.detail（后 id 可用）
   双入口：?reportId=xxx（我的报告/生成完成）与 ?planId=xxx（Stage 2 完成 result_ref=plan） */
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Button, Card, Collapse, Row, Col, Space, Skeleton, Alert, App as AntApp } from 'antd';
import BreadcrumbNav from '../../components/ui/BreadcrumbNav';
import ReportStepper from '../../components/ui/ReportStepper';
import MiniBar from '../../components/ui/MiniBar';
import DataNote from '../../components/ui/DataNote';
import AIGeneratedTag from '../../components/ui/AIGeneratedTag';
import ConfidenceBadge from '../../components/ui/ConfidenceBadge';
import ErrorState from '../../components/ui/ErrorState';
import PortraitSummaryCard from '../../components/business/PortraitSummaryCard';
import DirectionCard from '../../components/business/DirectionCard';
import GapTable from '../../components/business/GapTable';
import TaskItem from '../../components/business/TaskItem';
import SuggestionCard from '../../components/business/SuggestionCard';
import ConfidenceReasons from '../../components/business/ConfidenceReasons';
import PlanStageCapability from '../../components/business/PlanStageCapability';
import { reportsApi } from '../../services/reportsApi';
import { plansApi } from '../../services/plansApi';
import { ApiClientError } from '../../services/http';
import { toUserMessage } from '../../services/errorMapping';
import { toCareerDirection, toGapItem, toPlanTask, PHASE_NAME } from '../../utils/adapters';
import { formatDateTime } from '../../utils/formatDate';
import type { ApiPlanDetail, ApiReportDetail, CareerDirection, GapItem, PlanTask, RadarData } from '../../types';

/** 契约五维 key → 中文名（reports-contract dimensions） */
const DIMENSION_NAMES: Record<string, string> = {
  technical: '技术能力',
  project: '项目经验',
  academic: '学术背景',
  soft_skill: '软技能',
  industry_knowledge: '行业认知',
};

/** 页内锚点：与 ReportStepper 4 步一一对应 */
const SECTION_IDS = ['section-portrait', 'section-directions', 'section-gap', 'section-plan'] as const;

/** QA-BUG-017 置信度映射：gap_analysis.confidence（高/中/低 或 high/medium/low）→ 徽标级别；缺失返回 null（不渲染，避免老数据误导性「低置信度」） */
function resolveGapConfidence(report: ApiReportDetail | null): 'high' | 'medium' | 'low' | null {
  const raw = report?.gap_analysis?.confidence;
  if (raw === '高' || raw === 'high') return 'high';
  if (raw === '中' || raw === 'medium') return 'medium';
  if (raw === '低' || raw === 'low') return 'low';
  return null;
}

export default function ReportDetailPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const readOnly = searchParams.get('readonly') === '1';
  const reportIdParam = searchParams.get('reportId');
  const planIdParam = searchParams.get('planId');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ApiReportDetail | null>(null);
  const [plan, setPlan] = useState<ApiPlanDetail | null>(null);

  // 加载：优先 planId（Stage 2 完成态 result_ref=plan）；否则 reportId
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const loadByPlanId = async (planId: string) => {
      const planDetail = await plansApi.detail(planId);
      if (cancelled) return;
      setPlan(planDetail);
      if (planDetail.report_id) {
        try {
          const reportDetail = await reportsApi.detail(planDetail.report_id);
          if (cancelled) return;
          setReport(reportDetail);
        } catch {
          // 报告详情不可用时仅展示计划（差距/画像段走占位）
        }
      }
    };

    const loadByReportId = async (reportId: string) => {
      const detail = await reportsApi.detail(reportId);
      if (cancelled) return;
      setReport(detail);
      if (detail.plan?.id) {
        try {
          const planDetail = await plansApi.detail(detail.plan.id);
          if (cancelled) return;
          setPlan(planDetail);
        } catch {
          // 计划明细不可用时成长计划段走占位
        }
      }
    };

    (async () => {
      try {
        if (planIdParam) {
          await loadByPlanId(planIdParam);
        } else if (reportIdParam) {
          await loadByReportId(reportIdParam);
        } else {
          setError('缺少报告或计划 ID');
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiClientError ? toUserMessage(err) : '报告加载失败，请稍后重试');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [planIdParam, reportIdParam]);

  /** 页内锚点跳转（ReportStepper 完成步可回跳） */
  const scrollToSection = (step: number) => {
    const id = SECTION_IDS[step];
    if (!id) return;
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const radar = useMemo<RadarData | null>(() => {
    const portrait = report?.portrait;
    if (!portrait) return null;
    return {
      dimensions: Object.entries(portrait.dimensions ?? {}).map(([key, score]) => ({
        name: DIMENSION_NAMES[key] ?? key,
        score: Number(score),
      })),
    };
  }, [report]);

  const directions = useMemo<CareerDirection[]>(() => (report?.directions ?? []).map(toCareerDirection), [report]);

  const gaps = useMemo<GapItem[]>(() => {
    const items = report?.gap_analysis?.items ?? [];
    return (Array.isArray(items) ? items : []).map(toGapItem);
  }, [report]);

  const tasks = useMemo<PlanTask[]>(() => (plan ? plan.tasks.map(toPlanTask) : []), [plan]);

  const targetJob = report?.gap_analysis?.target_job ?? plan?.target_job ?? directions[0]?.name ?? '—';
  const matchScore = report?.gap_analysis?.match_score ?? directions[0]?.match ?? null;
  const gapConfidence = resolveGapConfidence(report);
  const gapReady = Boolean(report?.gap_analysis);
  const planReady = Boolean(plan && plan.tasks.length > 0);

  if (loading) {
    return (
      <div className="container-read page-body">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="container-read page-body">
        <ErrorState
          title={error ?? '报告数据加载失败'}
          onRetry={() => window.location.reload()}
          onBack={() => navigate(readOnly ? '/my-reports' : '/')}
        />
      </div>
    );
  }

  const portrait = report.portrait;
  const hasGap = gaps.length > 0;
  const gapReasons = report.gap_analysis?.confidence_reasons;
  const hasGapReasons = Boolean(gapReasons && ((gapReasons.supporting?.length ?? 0) > 0 || (gapReasons.concerns?.length ?? 0) > 0));
  const suggestion = report.suggestion;
  const hasSuggestion = Boolean(
    suggestion && (suggestion.summary || (suggestion.reasons?.length ?? 0) > 0 || suggestion.applicable_condition),
  );

  return (
    <div className="container-read page-body">
      <h1 className="sr-only">完整职业分析报告</h1>

      {readOnly && (
        <Alert
          type="info"
          showIcon
          message={`历史报告（生成于 ${formatDateTime(report.created_at)}）`}
          style={{ marginBottom: 'var(--space-6)', borderRadius: 'var(--radius-md)' }}
        />
      )}

      <BreadcrumbNav
        items={[
          { label: '仪表盘', path: '/' },
          { label: readOnly ? '我的报告' : '完整报告' },
        ]}
      />
      <ReportStepper current={3} onStepClick={scrollToSection} allClickable />
      <DataNote style={{ marginTop: 'var(--space-2)' }}>完整报告一页看全：职业画像 → 方向推荐 → 差距分析 → 成长计划；点击上方步骤可快速跳转</DataNote>

      {/* 0. AI 策略建议（v1.1/）：仅完整报告有 suggestion 时渲染；Stage 1 完成未选方向/生成失败/存量报告 → 整模块不渲染
          ：对齐页面其他模块「页面级 h2 标题 + 卡片」结构（h2 在卡片外，AIGeneratedTag 随标题行） */}
      {hasSuggestion && (
        <section aria-label="AI 策略建议" style={{ scrollMarginTop: 96, marginTop: 'var(--space-6)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
            <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600, margin: 0 }}>AI 策略建议</h2>
            <AIGeneratedTag />
          </div>
          <SuggestionCard suggestion={report.suggestion} onViewFullAnalysis={() => scrollToSection(0)} />
        </section>
      )}

      {/* 1. 画像摘要 */}
      <section id={SECTION_IDS[0]} aria-label="职业画像摘要" style={{ scrollMarginTop: 96, marginTop: 'var(--space-6)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
          <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600, margin: 0 }}>职业画像</h2>
        </div>
        {portrait && radar ? (
          <>
            <PortraitSummaryCard
              score={portrait.overall_score}
              radar={radar}
              date={formatDateTime(report.created_at)}
              percentileText={portrait.norm?.band ? `处于参考样本${portrait.norm.band}` : undefined}
              scoreNote={portrait.norm?.note ?? undefined}
              norm={portrait.norm}
              hideLink
            />
            {/* 优劣势（与画像页一致） */}
            <Row gutter={24} style={{ marginTop: 'var(--space-4)' }}>
              <Col xs={24} md={12} style={{ marginBottom: 'var(--space-4)' }}>
                <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 600, marginBottom: 'var(--space-3)' }}>你的优势</div>
                <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                  {(portrait.strengths ?? []).map((text) => (
                    <Card key={text} style={{ borderRadius: 'var(--radius-md)', background: 'var(--color-success-100)', border: 'none', borderLeft: '3px solid var(--color-success-600)' }} styles={{ body: { padding: 'var(--space-3)' } }}>
                      <div style={{ lineHeight: '24px' }}>{text}</div>
                    </Card>
                  ))}
                  {(portrait.strengths ?? []).length === 0 && <DataNote>暂无优势数据</DataNote>}
                </Space>
              </Col>
              <Col xs={24} md={12}>
                <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 600, marginBottom: 'var(--space-3)' }}>待提升</div>
                <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                  {(portrait.weaknesses ?? []).map((text) => (
                    <Card key={text} style={{ borderRadius: 'var(--radius-md)', background: 'var(--color-warning-100)', border: 'none', borderLeft: '3px solid var(--color-warning-600)' }} styles={{ body: { padding: 'var(--space-3)' } }}>
                      <div style={{ lineHeight: '24px' }}>{text}</div>
                    </Card>
                  ))}
                  {(portrait.weaknesses ?? []).length === 0 && <DataNote>暂无待提升项数据</DataNote>}
                </Space>
              </Col>
            </Row>
          </>
        ) : (
          <DataNote>暂无画像数据（报告可能尚未完成 Stage 1 生成）</DataNote>
        )}
      </section>

      {/* 2. 方向推荐 */}
      <section id={SECTION_IDS[1]} aria-label="方向推荐" style={{ scrollMarginTop: 96, marginTop: 'var(--space-8)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
          <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600, margin: 0 }}>方向推荐</h2>
        </div>
        <DataNote style={{ marginBottom: 'var(--space-4)' }}>
          市场数据为 AI 决策证据：方向基于画像与市场数据（薪资/趋势/热度/来源）推荐；匹配度低但薪资/热度高的方向，请结合学历与竞争门槛评估，优先选择匹配度更高的方向
        </DataNote>
        {directions.length > 0 ? (
          <Row gutter={24}>
            {directions.map((d) => (
              <Col xs={24} md={12} key={d.id} style={{ marginBottom: 'var(--space-4)' }}>
                <DirectionCard direction={d} readOnly expandable />
              </Col>
            ))}
          </Row>
        ) : (
          <Alert type="info" showIcon message="暂无方向推荐数据" description="可返回个人信息页补充画像后重新生成" style={{ borderRadius: 'var(--radius-md)' }} />
        )}
      </section>

      {/* 3. 目标岗位与差距分析 */}
      <section id={SECTION_IDS[2]} aria-label="目标岗位与差距分析" style={{ scrollMarginTop: 96, marginTop: 'var(--space-8)' }}>
        <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600, marginBottom: 'var(--space-4)' }}>目标岗位与差距分析</h2>
        <Card style={{ borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-4)' }} styles={{ body: { padding: 'var(--space-6)' } }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 'var(--space-4)' }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>目标岗位：{targetJob}</span>
                <AIGeneratedTag />
              </div>
              <div style={{ marginTop: 'var(--space-3)', maxWidth: 320 }}>
                <div style={{ marginBottom: 4, fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>
                  {matchScore != null ? '整体匹配度' : '计划进度'}
                </div>
                <MiniBar value={matchScore ?? plan?.progress ?? 0} />
              </div>
            </div>
            {gapConfidence && <ConfidenceBadge level={gapConfidence} note="基于画像与目标岗位 JD 要求计算" />}
          </div>
        </Card>

        {gapReady && hasGap ? (
          <>
            <GapTable gaps={gaps} />
            <DataNote style={{ marginTop: 'var(--space-3)' }}>每条差距项对应 JD 要求来源（jd_source）与你的现状判定依据（evidence），可追溯；数据基于目标岗位近 6 个月 JD 要求</DataNote>
            {hasGapReasons && (
              <div style={{ marginTop: 'var(--space-3)' }}>
                <ConfidenceReasons reasons={gapReasons} title="差距分析置信度说明" />
              </div>
            )}
          </>
        ) : (
          <Alert
            type="info"
            showIcon
            message="尚未生成差距分析"
            description={
              readOnly ? '该报告尚未完成差距分析生成' : '请先选择目标方向，生成差距分析与成长计划'
            }
            action={
              !readOnly && (
                <Button size="small" type="primary" onClick={() => navigate(`/report/directions?reportId=${report.id}`)}>
                  去选择方向
                </Button>
              )
            }
            style={{ borderRadius: 'var(--radius-md)' }}
          />
        )}
      </section>

      {/* 4. 成长计划 */}
      <section id={SECTION_IDS[3]} aria-label="成长计划" style={{ scrollMarginTop: 96, marginTop: 'var(--space-8)' }}>
        <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600, marginBottom: 'var(--space-4)' }}>成长计划</h2>
        {planReady ? (
          <Collapse
            defaultActiveKey={['short']}
            items={(['short', 'mid', 'long'] as const).map((key) => ({
              key,
              label: plan?.stages?.[key]?.label ?? PHASE_NAME[key],
              children: (
                <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                  <PlanStageCapability stage={plan?.stages?.[key]} />
                  {tasks.filter((t) => t.stage === key).map((task) => (
                    <TaskItem key={task.id} task={task} phaseName={plan?.stages?.[key]?.label ?? PHASE_NAME[key]} readOnly />
                  ))}
                  {tasks.filter((t) => t.stage === key).length === 0 && <DataNote>该阶段暂无任务</DataNote>}
                </Space>
              ),
            }))}
          />
        ) : (
          <Alert
            type="info"
            showIcon
            message="尚未生成成长计划"
            description={readOnly ? '该报告尚未完成差距分析与成长计划生成' : '选择目标方向并完成差距分析后，将自动生成成长计划'}
            action={
              !readOnly && (
                <Button size="small" type="primary" onClick={() => navigate(`/report/directions?reportId=${report.id}`)}>
                  去选择方向
                </Button>
              )
            }
            style={{ borderRadius: 'var(--radius-md)' }}
          />
        )}
      </section>

      {/* 底部操作区 */}
      <div style={{ marginTop: 'var(--space-8)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-3)' }}>
        {readOnly ? (
          <Button type="primary" onClick={() => navigate('/my-reports')}>
            返回我的报告
          </Button>
        ) : (
          <Button type="primary" onClick={() => { message.success('报告已保存到「我的报告」，可随时查看'); navigate('/my-reports'); }}>
            完成，查看我的报告
          </Button>
        )}
      </div>
    </div>
  );
}