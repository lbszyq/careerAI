/* Page-09 我的报告
   历史报告回访；详情 = 复用报告页只读态（决策②）
   未登录：空状态 + 登录引导；报告不可删除
   阶段二：GET /reports 真实列表（分页） */
import { useEffect, useState } from 'react';
import { Button, Card, Space, Skeleton } from 'antd';
import { useNavigate } from 'react-router-dom';
import Stat from '../components/ui/Stat';
import DataNote from '../components/ui/DataNote';
import ReportCard from '../components/business/ReportCard';
import EmptyState from '../components/ui/EmptyState';
import ErrorState from '../components/ui/ErrorState';
import { useAuth } from '../stores/useAuthStore';
import { useLoginModal } from '../hooks/useLoginModal';
import { reportsApi } from '../services/reportsApi';
import { ApiClientError } from '../services/http';
import { toUserMessage } from '../services/errorMapping';
import { toReportSummary } from '../utils/adapters';
import type { ReportSummary } from '../types';

export default function MyReportsPage() {
  const navigate = useNavigate();
  const { isLoggedIn } = useAuth();
  const { openLogin } = useLoginModal();

  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoggedIn) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    reportsApi
      .list(1, 10)
      .then((data) => {
        if (cancelled) return;
        setReports(data.items.map(toReportSummary));
        setTotal(data.total);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof ApiClientError ? toUserMessage(err) : '报告列表加载失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isLoggedIn]);
  /** /Q3：存在生成中（pending/running）报告时 5s 轮询刷新，完成后自动变为可查看 */
  const hasGenerating = reports.some((r) => r.status === 'pending' || r.status === 'running');

  useEffect(() => {
    if (!isLoggedIn || !hasGenerating) return;
    let stopped = false;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight || stopped) return;
      inFlight = true;
      try {
        const data = await reportsApi.list(1, 10);
        if (!stopped) {
          setReports(data.items.map(toReportSummary));
          setTotal(data.total);
          setError(null);
        }
      } catch (err) {
        if (!stopped && err instanceof ApiClientError) {
          setError(toUserMessage(err));
        }
      } finally {
        inFlight = false;
      }
    };
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [isLoggedIn, hasGenerating]);

  if (!isLoggedIn) {
    return (
      <div className="container-read page-body">
        <h1 className="sr-only">我的报告</h1>
        <EmptyState
          title="登录后查看你的历史报告"
          description="完成一次职业分析后，历次报告会保存在这里"
          actionText="去登录"
          onAction={openLogin}
        />
      </div>
    );
  }

  return (
    <div className="container-read page-body">
      <h1 className="sr-only">我的报告</h1>
      {/* 顶部统计区 */}
      <Card style={{ borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-6)' }} styles={{ body: { padding: 'var(--space-6)' } }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--space-6)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-8)' }}>
            <Stat value={`${total} 份报告`} label="历史报告总数" size="lg" />
            <DataNote>最近生成：{reports[0]?.date ?? '—'}</DataNote>
          </div>
          <Button type="primary" size="large" onClick={() => navigate('/profile')}>
            生成新报告
          </Button>
        </div>
      </Card>

      {/* 历史报告列表 */}
      {loading ? (
        <Skeleton active paragraph={{ rows: 4 }} />
      ) : error ? (
        <ErrorState title="报告列表加载失败" description={error} onRetry={() => window.location.reload()} />
      ) : reports.length === 0 ? (
        <EmptyState
          title="尚未生成报告"
          description="完成一次职业分析后，报告会出现在这里"
          actionText="立即开始分析"
          onAction={() => navigate('/profile')}
        />
      ) : (
        <Space direction="vertical" size="middle" style={{ width: '100%' }}>
          {reports.map((report) => (
            <ReportCard key={report.id} report={report} />
          ))}
        </Space>
      )}

      <DataNote style={{ marginTop: 'var(--space-6)' }}>历史报告不可删除；仅展示当前账号数据（数据隔离）</DataNote>
    </div>
  );
}
