/* Page-04 职业画像报告（体验核心）
    决策②：我的报告详情 = 复用本页只读态（readonly=1 时反馈条隐藏、按钮变「返回我的报告」）
   阶段二：GET /reports/{report_id} 真实数据；五维评分/常模对比/优劣势均来自报告详情 */
import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Button, Alert, Card, Row, Col, Space, Skeleton } from 'antd';
import BreadcrumbNav from '../../components/ui/BreadcrumbNav';
import ReportStepper from '../../components/ui/ReportStepper';
import Stat from '../../components/ui/Stat';
import DataNote from '../../components/ui/DataNote';
import AIGeneratedTag from '../../components/ui/AIGeneratedTag';
import ConfidenceBadge from '../../components/ui/ConfidenceBadge';
import ErrorState from '../../components/ui/ErrorState';
import RadarChart from '../../components/business/RadarChart';
import PortraitNormInfo from '../../components/business/PortraitNormInfo';
import { formatDateTime } from '../../utils/formatDate';
import { reportsApi } from '../../services/reportsApi';
import { ApiClientError } from '../../services/http';
import { toUserMessage } from '../../services/errorMapping';
import type { ApiReportDetail, RadarData } from '../../types';

/** 契约五维 key → 中文名（reports-contract dimensions） */
const DIMENSION_NAMES: Record<string, string> = {
  technical: '技术能力',
  project: '项目经验',
  academic: '学术背景',
  soft_skill: '软技能',
  industry_knowledge: '行业认知',
};

/** 常模分档（B-002：前 25%/中 50%/后 25%）→ 用户可见文案；无 band 时返回 null（：不渲染占位文案） */
function bandLabel(band: string | null | undefined): string | null {
  if (!band) return null;
  return `处于参考样本${band}`;
}

export default function PortraitReportPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const readOnly = searchParams.get('readonly') === '1';
  const reportId = searchParams.get('reportId');

  const [report, setReport] = useState<ApiReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
        setError(err instanceof ApiClientError ? toUserMessage(err) : '报告加载失败，请稍后重试');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  if (loading) {
    return (
      <div className="container-read page-body">
        <Card style={{ borderRadius: 'var(--radius-md)' }} styles={{ body: { padding: 'var(--space-6)' } }}>
          <Skeleton active paragraph={{ rows: 6 }} />
        </Card>
      </div>
    );
  }

  if (error || !report?.portrait) {
    return (
      <div className="container-read page-body">
        <h1 className="sr-only">职业画像报告</h1>
        <ErrorState
          title={error ?? '该报告暂无画像数据'}
          description={error ? undefined : '报告可能尚未生成或数据缺失'}
          onRetry={() => window.location.reload()}
          onBack={() => navigate('/my-reports')}
        />
      </div>
    );
  }

  const portrait = report.portrait;
  const radar: RadarData = {
    dimensions: Object.entries(portrait.dimensions ?? {}).map(([key, score]) => ({
      name: DIMENSION_NAMES[key] ?? key,
      score: Number(score),
    })),
  };
  const norm = portrait.norm;

  return (
    <div className="container-read page-body">
      <h1 className="sr-only">职业画像报告</h1>
      {/* 历史只读态横幅 */}
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
          { label: readOnly ? '我的报告' : '职业画像报告' },
        ]}
      />
      <ReportStepper current={0} />

      {/* 评分区 */}
      <Card style={{ borderRadius: 'var(--radius-lg)', marginTop: 'var(--space-4)' }} styles={{ body: { padding: 'var(--space-8)', textAlign: 'center' } }}>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
          <AIGeneratedTag />
          {portrait.confidence && <ConfidenceBadge level={portrait.confidence === '高' ? 'high' : portrait.confidence === '中' ? 'medium' : 'low'} note="整体置信度" />}
        </div>
        <Stat value={portrait.overall_score} label="综合竞争力评分" size="xl" color="accent" />
        {norm?.band && (
          <div style={{ marginTop: 'var(--space-3)', fontSize: 'var(--font-size-base)', fontWeight: 600, color: 'var(--color-accent-600)' }}>
            {bandLabel(norm.band)}
          </div>
        )}
        {norm?.note && (
          <div style={{ marginTop: 'var(--space-2)', display: 'flex', justifyContent: 'center' }}>
            <DataNote>{norm.note}</DataNote>
          </div>
        )}
        {/* v1.1：常模口径 + 置信度原因拆解 + 免责说明；字段缺失时区块隐藏 */}
        <div style={{ marginTop: 'var(--space-4)', textAlign: 'left', maxWidth: 560, marginLeft: 'auto', marginRight: 'auto' }}>
          <PortraitNormInfo norm={norm} />
        </div>
      </Card>

      {/* 能力雷达图 */}
      <Card style={{ borderRadius: 'var(--radius-md)', marginTop: 'var(--space-6)' }} styles={{ body: { padding: 'var(--space-6)' } }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
          <div style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600 }}>能力五维</div>
        </div>
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <div style={{ width: '100%', maxWidth: 480 }}>
            <RadarChart dimensions={radar.dimensions} />
          </div>
        </div>
      </Card>

      {/* 优劣势分析 */}
      <Row gutter={24} style={{ marginTop: 'var(--space-6)' }}>
        <Col xs={24} md={12} style={{ marginBottom: 'var(--space-6)' }}>
          <div style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600, marginBottom: 'var(--space-4)' }}>你的优势</div>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {(portrait.strengths ?? []).map((text) => (
              <Card key={text} style={{ borderRadius: 'var(--radius-md)', background: 'var(--color-success-100)', border: 'none', borderLeft: '3px solid var(--color-success-600)' }} styles={{ body: { padding: 'var(--space-4)' } }}>
                <div style={{ lineHeight: '24px' }}>{text}</div>
              </Card>
            ))}
            {(portrait.strengths ?? []).length === 0 && <DataNote>暂无优势数据</DataNote>}
          </Space>
        </Col>
        <Col xs={24} md={12}>
          <div style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600, marginBottom: 'var(--space-4)' }}>待提升</div>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {(portrait.weaknesses ?? []).map((text) => (
              <Card key={text} style={{ borderRadius: 'var(--radius-md)', background: 'var(--color-warning-100)', border: 'none', borderLeft: '3px solid var(--color-warning-600)' }} styles={{ body: { padding: 'var(--space-4)' } }}>
                <div style={{ lineHeight: '24px' }}>{text}</div>
              </Card>
            ))}
            {(portrait.weaknesses ?? []).length === 0 && <DataNote>暂无待提升项数据</DataNote>}
          </Space>
        </Col>
      </Row>

      {/* 底部操作区 */}
      <div style={{ marginTop: 'var(--space-8)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        {readOnly ? (
          <Button type="primary" onClick={() => navigate('/my-reports')}>
            返回我的报告
          </Button>
        ) : (
          <>
            <Button type="primary" size="large" onClick={() => navigate(`/report/directions?reportId=${report.id}`)}>
              下一步：查看推荐方向 →
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
