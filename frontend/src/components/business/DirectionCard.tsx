/* C-27 方向卡片 DirectionCard
   结构：岗位名称 + 匹配度 MiniBar + 「市场依据」证据块（薪资区间/趋势/热度/数据来源）
   主动纠偏：匹配度低但薪资/热度高的方向，突出进入门槛原因（学历/竞争）并引导评估替代方向
   展开态：薪资箱线图 + 推荐依据（学历/竞争度/证书/数据来源）
   状态：hover / 展开 / 已选（primary 2px 边框） */
import { useState } from 'react';
import { Card, Button } from 'antd';
import { ArrowUpOutlined, MinusOutlined, ArrowDownOutlined } from '@ant-design/icons';
import MiniBar from '../ui/MiniBar';
import SemanticTag from '../ui/SemanticTag';
import { trendSemantic, heatSemantic } from '../../utils/semanticTags';
import DataGradeBadge from '../ui/DataGradeBadge';
import BoxplotChart from './BoxplotChart';
import ConfidenceReasons from './ConfidenceReasons';
import SalaryComparison from './SalaryComparison';
import type { CareerDirection } from '../../types';

interface DirectionCardProps {
  direction: CareerDirection;
  /** ：聚合页只读态可展开查看薪资分布/推荐依据明细 */
  expandable?: boolean;
  selected?: boolean;
  onSelect?: (id: string) => void;
  readOnly?: boolean;
}

/** 主动纠偏触发阈值：匹配度低于此值视为「低匹配」 */
const MATCH_LOW = 60;
/** 高薪判定（k/月）：参考真实市场样本——应届 7-12k、中级 14-18k、头部 20k+ */
const HIGH_SALARY_K = 20;

const TrendIcon = ({ trend }: { trend: CareerDirection['trend'] }) => {
  if (trend === 'growth') return <ArrowUpOutlined style={{ marginRight: 4 }} />;
  if (trend === 'stable') return <MinusOutlined style={{ marginRight: 4 }} />;
  return <ArrowDownOutlined style={{ marginRight: 4 }} />;
};

const TrendLabel = { growth: '增长', stable: '稳定', decline: '下降' } as const;
const HeatLabel = { high: '高', medium: '中', low: '低' } as const;

export default function DirectionCard({ direction, selected, onSelect, readOnly, expandable }: DirectionCardProps) {
  const [expanded, setExpanded] = useState(false);

  /** 推荐依据：仅渲染非空字段，老数据缺字段优雅降级 */
  const detailRows = [
    { label: '学历要求', value: direction.educationRequirement },
    { label: '学历匹配度', value: direction.educationMatch },
    { label: '竞争度说明', value: direction.competitionNote },
    { label: '证书加分', value: direction.certificatesBonus },
    { label: '薪资说明', value: direction.salaryNote },
    { label: '数据来源', value: direction.dataSource },
  ].filter((row) => row.value);

  /** 主动纠偏：匹配度低但薪资/热度吸引力高 → 突出进入门槛（学历/竞争），引导评估替代方向 */
  const showCorrection =
    direction.match > 0 && direction.match < MATCH_LOW && (direction.heat === 'high' || direction.salaryMedian >= HIGH_SALARY_K);
  const correctionRows = [
    { label: '学历要求', value: direction.educationRequirement },
    { label: '学历匹配度', value: direction.educationMatch },
    { label: '竞争度说明', value: direction.competitionNote },
  ].filter((row) => row.value);

  return (
    <Card
      hoverable={!readOnly}
      onClick={() => {
        if (readOnly && !expandable) return;
        setExpanded((prev) => !prev);
      }}
      styles={{ body: { padding: 'var(--space-6)' } }}
      style={{
        borderRadius: 'var(--radius-md)',
        borderColor: selected ? 'var(--color-primary-600)' : 'var(--color-border-default)',
        borderWidth: selected ? 2 : 1,
        cursor: readOnly && !expandable ? 'default' : 'pointer',
        position: 'relative',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <div style={{ fontSize: 'var(--font-size-lg)', fontWeight: 600 }}>{direction.name}</div>

        {direction.recommendReason && (
          <div>
            <div style={{ marginBottom: 4, fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>推荐理由</div>
            <div
              style={{
                background: 'var(--color-primary-050)',
                borderLeft: '3px solid var(--color-primary-600)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-2) var(--space-3)',
                fontSize: 'var(--font-size-sm)',
                color: 'var(--color-text-primary)',
              }}
            >
              {direction.recommendReason}
            </div>
          </div>
        )}

        <div>
          <div style={{ marginBottom: 4, fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>匹配度</div>
          <MiniBar value={direction.match} />
        </div>

        {/* 市场依据证据块：薪资区间 / 趋势 / 热度 / 数据来源聚合突出 */}
        <div
          style={{
            background: 'var(--color-bg-subtle)',
            borderRadius: 'var(--radius-sm)',
            padding: 'var(--space-2) var(--space-3)',
            display: 'flex',
            flexDirection: 'column',
            gap: 'var(--space-1)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
            <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>市场依据</div>
            <DataGradeBadge grade={direction.dataGrade} />
          </div>
          <div className="tnum" style={{ fontSize: 'var(--font-size-base)', fontWeight: 600 }}>
            {direction.salaryMin}-{direction.salaryMax} k/月
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <SemanticTag semantic={trendSemantic(direction.trend)} icon={<TrendIcon trend={direction.trend} />}>
              {TrendLabel[direction.trend]}
            </SemanticTag>
            <SemanticTag semantic={heatSemantic(direction.heat)}>热度 {HeatLabel[direction.heat]}</SemanticTag>
            {direction.dataSource && (
              <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)' }}>来源：{direction.dataSource}</span>
            )}
          </div>
        </div>

        {/* 薪资对比行：期望薪资 vs 岗位薪资分位（null/no_data 组件内诚实隐藏） */}
        <SalaryComparison comparison={direction.salaryComparison} />

        {/* 主动纠偏：低匹配 × 高薪/高热度 → 展示进入门槛 + 替代方向引导 */}
        {showCorrection && (
          <div
            style={{
              background: 'var(--color-warning-100)',
              borderLeft: '3px solid var(--color-warning-600)',
              borderRadius: 'var(--radius-sm)',
              padding: 'var(--space-2) var(--space-3)',
            }}
          >
            <div style={{ fontSize: 'var(--font-size-xs)', fontWeight: 600, color: 'var(--color-warning-600)', marginBottom: 4 }}>
              匹配度较低，请先评估进入门槛
            </div>
            <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-primary)' }}>
              该方向薪资/热度吸引力较高，但匹配度仅 {direction.match}%：
            </div>
            {correctionRows.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 6, fontSize: 'var(--font-size-sm)' }}>
                {correctionRows.map((row) => (
                  <div key={row.label} style={{ display: 'flex', gap: 8 }}>
                    <span style={{ color: 'var(--color-text-secondary)', flexShrink: 0, width: 72 }}>{row.label}</span>
                    <span style={{ color: 'var(--color-text-primary)' }}>{row.value}</span>
                  </div>
                ))}
              </div>
            )}
            <div style={{ marginTop: 6, fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)' }}>
              建议优先评估匹配度更高的方向；如仍有意向，可先补齐学历/技能差距后再评估
            </div>
          </div>
        )}
      </div>

      {/* 展开态 */}
      {expanded && (
        <div style={{ marginTop: 'var(--space-6)', borderTop: '1px solid var(--color-divider)', paddingTop: 'var(--space-4)' }}>
          <div style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, marginBottom: 8 }}>薪资分布（k/月）</div>
          <BoxplotChart data={direction.boxplot} name={direction.name} height={240} />
          {detailRows.length > 0 && (
            <div style={{ marginTop: 'var(--space-4)' }}>
              <div style={{ fontSize: 'var(--font-size-sm)', fontWeight: 600, marginBottom: 8 }}>推荐依据</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 'var(--font-size-sm)' }}>
                {detailRows.map((row) => (
                  <div key={row.label} style={{ display: 'flex', gap: 8 }}>
                    <span style={{ color: 'var(--color-text-secondary)', flexShrink: 0, width: 72 }}>{row.label}</span>
                    <span style={{ color: 'var(--color-text-primary)' }}>{row.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {direction.confidenceReasons &&
            ((direction.confidenceReasons.supporting?.length ?? 0) > 0 || (direction.confidenceReasons.concerns?.length ?? 0) > 0) && (
            <div style={{ marginTop: 'var(--space-4)' }}>
              <ConfidenceReasons reasons={direction.confidenceReasons} title="置信度说明" />
            </div>
          )}
          {!readOnly && onSelect && (
            <div style={{ marginTop: 'var(--space-4)', textAlign: 'right' }}>
              <Button
                type={selected ? 'default' : 'primary'}
                size="small"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(direction.id);
                }}
              >
                {selected ? '已选择' : '选择此方向'}
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}