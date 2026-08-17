/* Page-08 我的计划（执行态 + 反馈闭环）
    决策③：执行态可勾选任务即时更新进度；报告流查看态在 page-06
   未登录：空状态 + 登录引导（交互规范）
   ：成果区（上传/编辑/删除）+ 申请重新评估（前置置灰/进行中/失败重试）
   + 重评结果 Drawer（四部分+应用/放弃）+ plans-contract v1.2 回显（completion_check 标签/存量降级） */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Button, Card, Collapse, Space, Skeleton, Tag, App as AntApp } from 'antd';
import ProgressRing from '../components/ui/ProgressRing';
import TaskItem from '../components/business/TaskItem';
import PlanStageCapability from '../components/business/PlanStageCapability';
import AchievementSection from '../components/business/AchievementSection';
import ReassessSection from '../components/business/ReassessSection';
import ReassessResultDrawer from '../components/business/ReassessResultDrawer';
import SemanticTag from '../components/ui/SemanticTag';
import DataNote from '../components/ui/DataNote';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import { useAuth } from '../stores/useAuthStore';
import { useLoginModal } from '../hooks/useLoginModal';
import { feedbackApi } from '../services/feedbackApi';
import { reportsApi } from '../services/reportsApi';
import { ApiClientError } from '../services/http';
import { toUserMessage } from '../services/errorMapping';
import { toPlanTask, PHASE_NAME } from '../utils/adapters';
import type { ApiAchievement, ApiLatestReassess, ApiPlanStage, ApiPlanTaskStatus, PlanTask } from '../types';

const LAST_PLAN_KEY = 'careerai:last_plan_id';
const ACTIVE_TASK_KEY = 'careerai:active_task';

export default function MyPlanPage() {
  const { isLoggedIn } = useAuth();
  const { openLogin } = useLoginModal();
  const { message } = AntApp.useApp();
  const navigate = useNavigate();

  // ：planId 优先级——URL 参数 → sessionStorage 旧标记 → 最近报告 plan.id（effect 内异步回退）
  const [planId, setPlanId] = useState<string | null>(() => {
    const urlPlanId = new URLSearchParams(window.location.search).get('planId');
    return urlPlanId ?? sessionStorage.getItem(LAST_PLAN_KEY);
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reportId, setReportId] = useState<string | null>(null);
  const [targetJob, setTargetJob] = useState<string>('');

  const [tasks, setTasks] = useState<PlanTask[]>([]);
  /** v1.1：阶段级能力化字段（goal/why/verify/resume_value/stage_completion），存量无字段时区块不渲染 */
  const [stages, setStages] = useState<Record<'short' | 'mid' | 'long', ApiPlanStage> | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  /** v1.2：反馈闭环回显 */
  /** 成果列表；null=存量计划无 achievements 字段（隐藏成果区），[]=显式空（展示空态引导） */
  const [achievements, setAchievements] = useState<ApiAchievement[] | null>(null);
  const [reassessEligible, setReassessEligible] = useState(false);
  const [reassessReason, setReassessReason] = useState<string | null>(null);
  const [latestReassess, setLatestReassess] = useState<ApiLatestReassess | null>(null);
  const [resultDrawer, setResultDrawer] = useState<{ open: boolean; reassessId: string | null }>({ open: false, reassessId: null });

  /** 加载/刷新计划（silent=true 静默刷新回显，不触发整页骨架） */
  const loadPlan = useCallback(
    async (silent = false) => {
      if (!planId) return;
      if (!silent) setLoading(true);
      setError(null);
      try {
        const plan = await feedbackApi.getPlan(planId);
        setReportId(plan.report_id);
        setTargetJob(plan.target_job);

        setTasks(plan.tasks.map(toPlanTask));
        setStages(plan.stages);
        setAchievements(plan.achievements ?? null);
        setReassessEligible(plan.reassess_eligible ?? false);
        setReassessReason(plan.reassess_eligible_reason ?? null);
        setLatestReassess(plan.latest_reassess ?? null);
        sessionStorage.setItem(LAST_PLAN_KEY, plan.id);
      } catch (err) {
        if (!silent) {
          setError(err instanceof ApiClientError ? toUserMessage(err) : '计划加载失败');
        } else {
          message.error(err instanceof ApiClientError ? toUserMessage(err) : '计划数据刷新失败，请稍后重试');
        }
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [planId, message],
  );

  useEffect(() => {
    if (!isLoggedIn) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    if (!planId) {
      // ：无 URL/sessionStorage 时回退最近报告关联计划（detail.plan?.id）
      setLoading(true);
      setError(null);
      (async () => {
        try {
          const list = await reportsApi.list(1, 1);
          if (cancelled) return;
          if (list.items.length > 0) {
            const detail = await reportsApi.detail(list.items[0].id);
            if (cancelled) return;
            const fallbackPlanId = detail?.plan?.id ?? null;
            if (fallbackPlanId) {
              setPlanId(fallbackPlanId); // 回填后 effect 重跑 → 加载计划
              return;
            }
          }
          setLoading(false); // 回退失败（无报告/最近报告无计划）→ 空态
        } catch {
          if (!cancelled) setLoading(false); // 查询失败 → 空态
        }
      })();
      return () => {
        cancelled = true;
      };
    }
    void loadPlan();
    return () => {
      cancelled = true;
    };
  }, [isLoggedIn, planId, loadPlan]);

  const effectiveDoneCount = useMemo(
    () => tasks.filter((t) => t.status === 'done' || t.coveredByAchievement).length,
    [tasks],
  );
  const achievementCount = achievements?.length ?? 0;
  const passedStageCount = useMemo(
    () => (stages ? Object.values(stages).filter((s) => s.completion_check === 'pass').length : 0),
    [stages],
  );
  const progressPercent = tasks.length > 0 ? Math.round((effectiveDoneCount / tasks.length) * 100) : 0;

  const handleToggle = useCallback(
    async (taskId: string, checked: boolean) => {
      if (!planId) return;
      const prev = tasks;
      // 乐观更新
      setTasks((cur) => cur.map((t) => (t.id === taskId ? { ...t, status: checked ? 'done' : 'pending' } : t)));
      try {
        await feedbackApi.updateTaskStatus(planId, taskId, (checked ? 'done' : 'todo') as ApiPlanTaskStatus);

        message.success(checked ? '任务完成' : '已标记未完成');
        // ：任务状态影响重评前置（非 todo 任务），静默刷新回显
        void loadPlan(true);
      } catch (err) {
        // 回滚
        setTasks(prev);
        message.error(err instanceof ApiClientError ? toUserMessage(err) : '更新失败，请稍后重试');
      }
    },
    [planId, tasks, message, loadPlan],
  );

  // 重新生成计划（需已完成差距分析；后端 3205 兜底）
  const handleRegenerate = async () => {
    if (!reportId) {
      message.warning('暂无可用报告');
      return;
    }
    setRegenerating(true);
    try {
      const accepted = await reportsApi.regeneratePlan(reportId);
      message.info('正在基于最新市场数据重新生成计划…');
      sessionStorage.setItem(ACTIVE_TASK_KEY, accepted.task_id);
      navigate(`/generating?task_id=${accepted.task_id}&stage=2`);
    } catch (err) {
      message.error(err instanceof ApiClientError ? toUserMessage(err) : '提交失败，请稍后重试');
    } finally {
      setRegenerating(false);
    }
  };

  /** 打开重评结果 Drawer（从 latest_reassess.result_ref 解析重评记录 ID） */
  const openResultDrawer = useCallback(() => {
    const ref = latestReassess?.result_ref;
    const reassessId = ref ? ref.split('/').filter(Boolean).pop() ?? null : null;
    setResultDrawer({ open: true, reassessId });
  }, [latestReassess]);

  if (!isLoggedIn) {
    return (
      <div className="container-read page-body">
        <h1 className="sr-only">我的计划</h1>
        <EmptyState
          title="登录后查看你的成长计划"
          description="完成一次职业分析后，成长计划会复制到这里执行"
          actionText="去登录"
          onAction={openLogin}
        />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="container-read page-body">
        <Skeleton active paragraph={{ rows: 6 }} />
      </div>
    );
  }

  if (!planId) {
    return (
      <div className="container-read page-body">
        <h1 className="sr-only">我的计划</h1>
        <EmptyState
          title="暂无成长计划"
          description="完成一次职业分析并生成差距分析后，成长计划会出现在这里"
          actionText="开始职业分析"
          onAction={() => navigate('/profile')}
        />
      </div>
    );
  }

  if (error || tasks.length === 0) {
    return (
      <div className="container-read page-body">
        <ErrorState
          title={error ?? '暂无计划任务'}
          description={error ? undefined : '该计划暂无任务数据'}
          onRetry={() => window.location.reload()}
          onBack={() => navigate('/')}
        />
      </div>
    );
  }

  const phases = (['short', 'mid', 'long'] as const).map((key) => ({
    key,
    name: PHASE_NAME[key],
    tasks: tasks.filter((t) => t.stage === key),
  }));

  return (
    <div className="container-read page-body">
      <h1 className="sr-only">我的计划</h1>
      {/* 目标区 */}
      <Card style={{ borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-6)' }} styles={{ body: { padding: 'var(--space-6)' } }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--space-6)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-6)' }}>
            <ProgressRing percent={progressPercent} size={96} />
            <div>
              <div style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>目标岗位：{targetJob}</div>
              <div className="tnum" style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
                {`完成 ${effectiveDoneCount}/${tasks.length} 项${achievements !== null ? ` · 成果 ${achievementCount}` : ''}${stages !== null ? ` · 阶段通过 ${passedStageCount}/3` : ''}`}
              </div>
              {/* v1.2：最近一次重评时间（如有） */}
              {latestReassess?.status === 'succeeded' && latestReassess.finished_at && (
                <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>
                  最近重评：{latestReassess.finished_at.slice(0, 16).replace('T', ' ')}
                </div>
              )}
            </div>
          </div>
          <Button type="text" loading={regenerating} onClick={() => void handleRegenerate()}>
            重新生成计划
          </Button>
        </div>
      </Card>

      {/* 任务列表（阶段区带 completion_check 标签，v1.2） */}
      <Collapse
        defaultActiveKey={['short']}
        items={phases.map((phase) => ({
          key: phase.key,
          label: (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              {phase.name}
              <CompletionCheckTag check={stages?.[phase.key]?.completion_check} />
            </span>
          ),
          children: (
            <Space direction="vertical" size="middle" style={{ width: '100%' }}>
              <PlanStageCapability stage={stages?.[phase.key]} />
              {phase.tasks.map((task) => (
                <TaskItem key={task.id} task={task} phaseName={phase.name} onToggle={(id, checked) => void handleToggle(id, checked)} />
              ))}
              {phase.tasks.length === 0 && <DataNote>该阶段暂无任务</DataNote>}
            </Space>
          ),
        }))}
      />

      {/* 成果区（v1.2/）：存量计划无 achievements 字段时整区隐藏（优雅降级） */}
      {achievements !== null && (
        <Card style={{ borderRadius: 'var(--radius-md)', marginTop: 'var(--space-6)' }} styles={{ body: { padding: 'var(--space-6)' } }}>
          <AchievementSection planId={planId} achievements={achievements} tasks={tasks} onChanged={() => void loadPlan(true)} />
        </Card>
      )}

      {/* 申请重新评估（v1.2/） */}
      <ReassessSection
        planId={planId}
        eligible={reassessEligible}
        reason={reassessReason}
        latestReassess={latestReassess}
        onPlanChanged={() => void loadPlan(true)}
        onViewResult={openResultDrawer}
      />

      <DataNote style={{ marginTop: 'var(--space-6)' }}>
        重新生成将基于当前画像与最新市场数据更新计划；原计划将保留在历史报告
      </DataNote>

      {/* 重评结果 Drawer（四部分 + 应用/放弃） */}
      <ReassessResultDrawer
        open={resultDrawer.open}
        planId={planId}
        reassessId={resultDrawer.reassessId}
        onClose={() => setResultDrawer((cur) => ({ ...cur, open: false }))}
        onDecided={() => void loadPlan(true)}
      />
    </div>
  );
}

/** 阶段完成校验标签（v1.2）：pass=通过 / fail=未通过 / unchecked=未校验；字段缺失不渲染（存量降级） */
function CompletionCheckTag({ check }: { check?: 'pass' | 'fail' | 'unchecked' | null }) {
  if (!check) return null;
  if (check === 'pass') {
    return <SemanticTag semantic="success">阶段校验通过</SemanticTag>;
  }
  if (check === 'fail') {
    return <SemanticTag semantic="danger">阶段校验未通过</SemanticTag>;
  }
  return (
    <Tag
      style={{
        borderRadius: 'var(--radius-pill)',
        color: 'var(--color-text-tertiary)',
        background: 'var(--color-bg-subtle)',
        borderColor: 'transparent',
        height: 24,
        lineHeight: '22px',
        padding: '0 10px',
        fontSize: 'var(--font-size-xs)',
      }}
    >
      未校验
    </Tag>
  );
}
