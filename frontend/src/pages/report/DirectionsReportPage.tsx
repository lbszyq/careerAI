/* Page-05 职业方向推荐（体验核心）
   阶段二：GET /reports/{report_id} 的方向数据；排序在前端对契约数据做客户端排序
   （契约方向数据为报告级快照，无独立筛选端点）
   选择方向 → POST /reports/{id}/gap → task_id → 生成中页 stage=2 */
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams, useNavigate, Link } from 'react-router-dom';
import { Button, Alert, Row, Col, Select, Space, Skeleton, App as AntApp } from 'antd';
import BreadcrumbNav from '../../components/ui/BreadcrumbNav';
import ReportStepper from '../../components/ui/ReportStepper';
import DataNote from '../../components/ui/DataNote';
import ErrorState from '../../components/ui/ErrorState';
import DirectionCard from '../../components/business/DirectionCard';
import { reportsApi } from '../../services/reportsApi';
import { ApiClientError } from '../../services/http';
import { toUserMessage } from '../../services/errorMapping';
import { toCareerDirection } from '../../utils/adapters';
import type { ApiReportDetail, CareerDirection } from '../../types';

const ACTIVE_TASK_KEY = 'careerai:active_task';

export default function DirectionsReportPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { message } = AntApp.useApp();
  const readOnly = searchParams.get('readonly') === '1';
  const reportId = searchParams.get('reportId');

  const [report, setReport] = useState<ApiReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [sortBy, setSortBy] = useState<'match' | 'salary'>('match');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (!reportId) {
      setError('缺少报告 ID');
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    reportsApi
      .detail(reportId)
      .then((data) => {
        if (cancelled) return;
        setReport(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiClientError ? toUserMessage(err) : '方向数据加载失败，请稍后重试');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  const allDirections = useMemo<CareerDirection[]>(() => (report?.directions ?? []).map(toCareerDirection), [report]);

  // 客户端排序（契约方向数据为报告快照，仅排序生效）
  const sortedDirections = useMemo(() => {
    const list = [...allDirections];
    if (sortBy === 'salary') list.sort((a, b) => b.salaryMedian - a.salaryMedian);
    else list.sort((a, b) => b.match - a.match);
    return list;
  }, [allDirections, sortBy]);

  const handleSelectDirection = async () => {
    if (!selectedId || !reportId) return;
    const target = allDirections.find((d) => d.id === selectedId);
    setSubmitting(true);
    try {
      const accepted = await reportsApi.createGap(reportId, selectedId);
      message.success(`已选择目标方向：${target?.name}，正在生成差距分析与成长计划`);
      sessionStorage.setItem(ACTIVE_TASK_KEY, accepted.task_id);
      navigate(`/generating?task_id=${accepted.task_id}&stage=2`);
    } catch (err) {
      message.error(err instanceof ApiClientError ? toUserMessage(err) : '提交失败，请稍后重试');
    } finally {
      setSubmitting(false);
    }
  };

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
          title={error ?? '方向数据加载失败'}
          onRetry={() => window.location.reload()}
          onBack={() => navigate(readOnly ? '/my-reports' : '/report/portrait')}
        />
      </div>
    );
  }

  return (
    <div className="container-read page-body">
      <BreadcrumbNav
        items={[
          { label: '仪表盘', path: '/' },
          { label: '职业画像报告', path: `/report/portrait?reportId=${report.id}` },
          { label: readOnly ? '我的报告' : '职业方向推荐' },
        ]}
      />
      <ReportStepper current={1} />

      {/* 标题 */}
      <div style={{ marginTop: 'var(--space-4)', marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 600, margin: 0 }}>为你推荐的职业方向</h1>
        <DataNote style={{ marginTop: 8 }}>基于你的画像与市场数据，推荐 {allDirections.length} 个方向；排序默认按匹配度</DataNote>
      </div>

      {/* 排序栏 */}
      <Space size="middle" wrap style={{ marginBottom: 'var(--space-6)' }}>
        <Select
          placeholder="排序"
          value={sortBy}
          onChange={(v) => setSortBy(v)}
          disabled={readOnly}
          style={{ minWidth: 140 }}
          aria-label="排序方式"
          options={[
            { label: '按匹配度', value: 'match' },
            { label: '按薪资中位数', value: 'salary' },
          ]}
        />
      </Space>

      {/* 方向卡片 */}
      <Row gutter={24}>
        {sortedDirections.map((d) => (
          <Col xs={24} md={12} key={d.id} style={{ marginBottom: 'var(--space-6)' }}>
            <DirectionCard
              direction={d}
              selected={selectedId === d.id}
              onSelect={(id) => setSelectedId((prev) => (prev === id ? null : id))}
              readOnly={readOnly}
            />
          </Col>
        ))}
        {sortedDirections.length === 0 && (
          <Col span={24}>
            <Alert type="info" showIcon message="暂无方向推荐数据" description="可返回个人信息页补充画像后重新生成" style={{ borderRadius: 'var(--radius-md)' }} />
          </Col>
        )}
      </Row>

      {/* 底部操作区 */}
      {readOnly ? (
        <div style={{ marginTop: 'var(--space-8)', textAlign: 'right' }}>
          <Button type="primary" onClick={() => navigate('/my-reports')}>
            返回我的报告
          </Button>
        </div>
      ) : (
        <>
          <Alert
            type={selectedId ? 'success' : 'info'}
            showIcon
            message={selectedId ? `已选择：${allDirections.find((d) => d.id === selectedId)?.name}` : '展开卡片选择目标方向'}
            style={{ borderRadius: 'var(--radius-md)' }}
          />
          <div style={{ marginTop: 'var(--space-6)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Link to={`/report/portrait?reportId=${report.id}`}>← 上一步（职业画像）</Link>
            <Button type="primary" size="large" disabled={!selectedId} loading={submitting} onClick={() => void handleSelectDirection()}>
              选择此方向
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
