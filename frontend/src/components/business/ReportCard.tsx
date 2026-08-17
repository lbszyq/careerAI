/* C-29 报告卡片 ReportCard（我的报告）
   内容：报告类型 Tag + 生成日期 + 综合评分摘要 + 目标方向 + 「查看详情」入口
   /Q3：按 status 渲染——pending/running 生成中卡片（Spin+阶段文案），failed 失败卡片 */
import { Card, Spin } from 'antd';
import { CloseCircleOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import SemanticTag from '../ui/SemanticTag';
import type { ReportSummary } from '../../types';

const typeLabel: Record<string, string> = {
  portrait: '职业画像',
  directions: '方向推荐',
  gap: '差距分析',
  plan: '成长计划',
};

function detailPath(report: ReportSummary): string {
  // ：详情统一落完整报告聚合页（一页看全画像/方向/差距/计划，用户决策方案 C）
  return `/report/detail?readonly=1&reportId=${report.id}`;
}

interface ReportCardProps {
  report: ReportSummary;
}

const REPORT_TITLE: Record<ReportSummary['stage'], string> = {
  stage1: '职业画像报告',
  stage2: '差距分析与成长计划',
};

export default function ReportCard({ report }: ReportCardProps) {
  /* 生成中（pending/running）：Spin + 阶段文案 + 生成进度入口（列表含生成中记录） */
  if (report.status === 'pending' || report.status === 'running') {
    return (
      <Card style={{ borderRadius: 'var(--radius-md)' }} styles={{ body: { padding: 'var(--space-4) var(--space-6)' } }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)', minWidth: 0 }}>
            <Spin size="small" />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 600 }}>
                {REPORT_TITLE[report.stage]}生成中
              </div>
              <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
                {report.status === 'running' ? 'AI 正在分析，请稍候' : '排队中，即将开始分析'} · {report.date} 开始 · 完成后自动变为可查看
              </div>
            </div>
          </div>
          <Link to={`/generating?task_id=${report.id}&stage=${report.stage === 'stage2' ? '2' : '1'}`} style={{ whiteSpace: 'nowrap' }}>
            查看生成进度 →
          </Link>
        </div>
      </Card>
    );
  }

  /* 生成失败（failed）：不可查看详情，引导重新生成 */
  if (report.status === 'failed') {
    return (
      <Card style={{ borderRadius: 'var(--radius-md)' }} styles={{ body: { padding: 'var(--space-4) var(--space-6)' } }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)', minWidth: 0 }}>
          <CloseCircleOutlined style={{ fontSize: 20, color: 'var(--color-danger-600)' }} aria-label="生成失败" />
          <div>
            <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 600 }}>{REPORT_TITLE[report.stage]}生成失败</div>
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>{report.date} 发起 · 可回到首页重新发起分析</div>
          </div>
        </div>
      </Card>
    );
  }

  /* 已完成（completed） */
  return (
    <Card hoverable style={{ borderRadius: 'var(--radius-md)' }} styles={{ body: { padding: 'var(--space-4) var(--space-6)' } }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-4)', flexWrap: 'wrap', minWidth: 0 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {report.types.map((t) => (
              <SemanticTag key={t} semantic="info">{typeLabel[t]}</SemanticTag>
            ))}
          </div>
          <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>{report.date}</span>
          <span className="tnum" style={{ fontSize: 'var(--font-size-lg)', fontWeight: 700, color: 'var(--color-accent-600)' }}>
            {report.score} 分
          </span>
          {report.direction && (
            <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>目标方向：{report.direction}</span>
          )}
        </div>
        <Link to={detailPath(report)} style={{ whiteSpace: 'nowrap' }}>
          查看详情 →
        </Link>
      </div>
    </Card>
  );
}
