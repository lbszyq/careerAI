/* Page-06 差距分析 + 成长计划（体验核心）
    决策③：报告流查看态任务不可勾选（readOnly）；「开始执行计划」→ 跳我的计划执行态
   阶段二：
   - ?planId=xxx → GET /plans/{plan_id}（生成流程 stage2 完成后跳转）
   - ?reportId=xxx → GET /reports/{report_id} 的 gap_analysis + plan 摘要，任务明细经 plan.id 拉取 */
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import { Button, Card, Collapse, Space, Skeleton, App as AntApp } from 'antd';
import BreadcrumbNav from '../../components/ui/BreadcrumbNav';
import ReportStepper from '../../components/ui/ReportStepper';
import MiniBar from '../../components/ui/MiniBar';
import DataNote from '../../components/ui/DataNote';
import AIGeneratedTag from '../../components/ui/AIGeneratedTag';
import ConfidenceBadge from '../../components/ui/ConfidenceBadge';
import ErrorState from '../../components/ui/ErrorState';
import GapTable from '../../components/business/GapTable';
import TaskItem from '../../components/business/TaskItem';
import ConfidenceReasons from '../../components/business/ConfidenceReasons';
import PlanStageCapability from '../../components/business/PlanStageCapability';
import { reportsApi } from '../../services/reportsApi';
import { plansApi } from '../../services/plansApi';
import { ApiClientError } from '../../services/http';
import { toUserMessage } from '../../services/errorMapping';
import { toGapItem, toPlanTask, PHASE_NAME } from '../../utils/adapters';
import type { ApiPlanDetail, ApiReportDetail, GapItem, PlanTask } from '../../types';

/** QA-BUG-017 置信度映射：gap_analysis.confidence（高/中/低 或 high/medium/low）→ 徽标级别；缺失返回 null（不渲染，避免老数据误导性「低置信度」） */
function resolveGapConfidence(report: ApiReportDetail | null): 'high' | 'medium' | 'low' | null {
  const raw = report?.gap_analysis?.confidence;
  if (raw === '高' || raw === 'high') return 'high';
  if (raw === '中' || raw === 'medium') return 'medium';
  if (raw === '低' || raw === 'low') return 'low';
  return null;
}

export default function GapPlanReportPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const readOnly = searchParams.get('readonly') === '1';
  const planIdParam = searchParams.get('planId');
  const reportIdParam = searchParams.get('reportId');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ApiReportDetail | null>(null);
  const [plan, setPlan] = useState<ApiPlanDetail | null>(null);

  // 加载：优先 planId；否则 reportId → plan 摘要 → 明细
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    const loadByPlanId = async (planId: string) => {
      const detail = await plansApi.detail(planId);
      if (cancelled) return;
      setPlan(detail);
      // QA-BUG-016：?planId 路径差距清单数据源为 report.gap_analysis.items，需补调报告详情
      if (detail.report_id) {
        try {
          const reportDetail = await reportsApi.detail(detail.report_id);
          if (cancelled) return;
          setReport(reportDetail);
        } catch {
          // 报告详情不可用时仅展示计划，差距清单走空态提示
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
          // 计划明细不可用时仅展示报告内嵌摘要
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
          setError('缺少计划或报告 ID');
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiClientError ? toUserMessage(err) : '数据加载失败，请稍后重试');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [planIdParam, reportIdParam]);

  const gaps = useMemo<GapItem[]>(() => {
    const items = report?.gap_analysis?.items ?? [];
    // 契约适配：weight=number/level=中文 → 展示枚举
    return (Array.isArray(items) ? items : []).map(toGapItem);
  }, [report]);

  const tasks = useMemo<PlanTask[]>(() => (plan ? plan.tasks.map(toPlanTask) : []), [plan]);

  const handleStartPlan = () => {
    if (!plan) {
      message.warning('暂无可用计划');
      return;
    }
    message.success('计划已复制到「我的计划」执行态');
    navigate(`/my-plan?planId=${plan.id}`);
  };

  if (loading) {
    return (
      <div className="container-read page-body">
        <Skeleton active paragraph={{ rows: 8 }} />
      </div>
    );
  }

  if (error || (!report && !plan)) {
    return (
      <div className="container-read page-body">
        <ErrorState
          title={error ?? '差距分析与计划数据加载失败'}
          onRetry={() => window.location.reload()}
          onBack={() => navigate(readOnly ? '/my-reports' : '/report/directions')}
        />
      </div>
    );
  }

  const targetJob = plan?.target_job ?? report?.gap_analysis?.target_job ?? '—';
  const matchScore = report?.gap_analysis?.match_score;
  const planProgress = plan?.progress ?? report?.plan?.progress ?? 0;
  const gapReasons = report?.gap_analysis?.confidence_reasons;
  const hasGapReasons = Boolean(gapReasons && ((gapReasons.supporting?.length ?? 0) > 0 || (gapReasons.concerns?.length ?? 0) > 0));

  // QA-BUG-017 前端防御：gap_analysis.confidence 缺失（老数据）时不渲染徽标，避免误导性「低置信度」
  const gapConfidence = resolveGapConfidence(report);

  const phases = (['short', 'mid', 'long'] as const).map((key) => ({
    key,
    name: plan?.stages?.[key]?.label ?? PHASE_NAME[key],
    tasks: tasks.filter((t) => t.stage === key),
  }));

  return (
    <div className="container-read page-body">
      <h1 className="sr-only">差距分析与成长计划</h1>
      <BreadcrumbNav
        items={[
          { label: '仪表盘', path: '/' },
          { label: '职业画像报告', path: `/report/portrait?reportId=${report?.id ?? ''}` },
          { label: '职业方向推荐', path: `/report/directions?reportId=${report?.id ?? ''}` },
          { label: readOnly ? '我的报告' : '差距分析' },
        ]}
      />
      <ReportStepper current={2} />

      {/* 目标区 */}
      <Card style={{ borderRadius: 'var(--radius-md)', marginTop: 'var(--space-4)' }} styles={{ body: { padding: 'var(--space-6)' } }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 'var(--space-4)' }}>
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>目标岗位：{targetJob}</span>
              <AIGeneratedTag />
            </div>
            <div style={{ marginTop: 'var(--space-4)', maxWidth: 320 }}>
              <div style={{ marginBottom: 4, fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>
                {matchScore != null ? '整体匹配度' : '计划进度'}
              </div>
              <MiniBar value={matchScore ?? planProgress} />
            </div>
          </div>
          {gapConfidence && <ConfidenceBadge level={gapConfidence} note="基于画像与目标岗位 JD 要求计算" />}
        </div>
      </Card>

      {/* 差距分析 */}
      <section aria-label="技能差距清单" style={{ marginTop: 'var(--space-8)' }}>
        <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600 }}>技能差距清单</h2>
        {gaps.length > 0 ? (
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
          <DataNote>暂无差距分析数据（需先完成 Stage 2 生成）</DataNote>
        )}
      </section>

      {/* 成长计划（查看态） */}
      <section aria-label="成长计划" style={{ marginTop: 'var(--space-8)' }}>
        <h2 style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600 }}>成长计划</h2>
        {tasks.length > 0 ? (
          <Collapse
            defaultActiveKey={['short']}
            items={phases.map((phase) => ({
              key: phase.key,
              label: phase.name,
              children: (
                <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                  <PlanStageCapability stage={plan?.stages?.[phase.key]} />
                  {phase.tasks.map((task) => (
                    <TaskItem key={task.id} task={task} phaseName={phase.name} readOnly />
                  ))}
                  {phase.tasks.length === 0 && <DataNote>该阶段暂无任务</DataNote>}
                </Space>
              ),
            }))}
          />
        ) : (
          <DataNote>暂无成长计划任务（需先完成 Stage 2 生成）</DataNote>
        )}
      </section>

      {/* 反馈条 + 底部操作区 */}
      {readOnly ? (
        <div style={{ marginTop: 'var(--space-8)', textAlign: 'right' }}>
          <Button type="primary" onClick={() => navigate('/my-reports')}>
            返回我的报告
          </Button>
        </div>
      ) : (
        <>
          <div style={{ marginTop: 'var(--space-6)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Link to={`/report/directions?reportId=${report?.id ?? ''}`}>← 上一步（方向推荐）</Link>
            <Button type="primary" size="large" onClick={handleStartPlan}>
              开始执行计划 →
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
