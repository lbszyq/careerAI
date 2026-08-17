/* C-28 画像摘要卡 PortraitSummaryCard
   左 = 评分 Stat + 常模说明 DataNote；右 = 雷达图缩略（240×180）
   阶段二：支持 percentileText/scoreNote 覆盖（契约常模为分档文案，非精确百分比） */
import { Card } from 'antd';
import { Link } from 'react-router-dom';
import Stat from '../ui/Stat';
import DataNote from '../ui/DataNote';
import RadarChart from './RadarChart';
import PortraitNormInfo from './PortraitNormInfo';
import type { ApiPortraitNorm, RadarData } from '../../types';

interface PortraitSummaryCardProps {
  /** ：聚合页内隐藏「查看完整报告」跳转（避免无 reportId 链接） */
  /** ：报告 id，有值时链接跳完整报告聚合页；无值时不渲染链接（修复仪表盘坏链） */
  reportId?: string;
  hideLink?: boolean;
  score: number;
  radar: RadarData;
  date?: string;
  percentileText?: string;
  scoreNote?: string;
  /** v1.1：常模口径（cohort/sample_size/contains_employed/confidence）+ 置信度原因 + 免责说明；缺失时不渲染 */
  norm?: ApiPortraitNorm | null;
}

export default function PortraitSummaryCard({ score, radar, date, percentileText, scoreNote, norm, hideLink, reportId }: PortraitSummaryCardProps) {
  // ：score 为 null/undefined/非数字时展示 '--'，避免渲染 NaN/undefined
  const scoreLabel: string | number = typeof score === 'number' && Number.isFinite(score) ? score : '--';
  return (
    <Card
      style={{ borderRadius: 'var(--radius-md)', height: '100%' }}
      styles={{ body: { padding: 'var(--space-6)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-6)', flexWrap: 'wrap' } }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', minWidth: 160 }}>
        <Stat value={scoreLabel} label="综合竞争力评分" size="xl" color="accent" />
        {percentileText && (
          <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 600 }}>
            {percentileText}
          </div>
        )}
        {scoreNote && <DataNote>{scoreNote}</DataNote>}
        <PortraitNormInfo norm={norm} />
        {date && <DataNote>最近生成：{date}</DataNote>}
        {!hideLink && reportId && (<Link to={`/report/detail?readonly=1&reportId=${reportId}`} style={{ marginTop: 'var(--space-2)' }}>
          查看完整报告
        </Link>)}
      </div>
      <div style={{ width: 240, flexShrink: 0 }}>
        <RadarChart dimensions={radar.dimensions} height={180} minHeight={160} />
      </div>
    </Card>
  );
}
