/* C-31 差距表格 GapTable
   列：技能名称 | 权重（MiniBar 细条）| 当前状态（Tag）| JD 要求（来源）| 判定依据（证据）（透传 契约字段）
   表头 bg-subtle；行间 1px divider */
import { Table, type TableProps } from 'antd';
import MiniBar from '../ui/MiniBar';
import SemanticTag from '../ui/SemanticTag';
import DataGradeBadge from '../ui/DataGradeBadge';
import type { GapItem } from '../../types';
import type { TagSemantic } from '../../utils/semanticTags';

const weightMap: Record<GapItem['weight'], { value: number; label: string }> = {
  high: { value: 90, label: '高' },
  medium: { value: 60, label: '中' },
  low: { value: 30, label: '低' },
};

const statusMap: Record<GapItem['status'], { semantic: TagSemantic; label: string }> = {
  have: { semantic: 'success', label: '已具备' },
  partial: { semantic: 'warning', label: '部分具备' },
  lack: { semantic: 'danger', label: '不具备' },
};

/** 防御兜底：未知权重/状态枚举不抛错，渲染中性占位 */
const WEIGHT_UNKNOWN = { value: 0, label: '—' };
const STATUS_UNKNOWN = { semantic: 'info' as TagSemantic, label: '—' };

interface GapTableProps {
  gaps: GapItem[];
}

export default function GapTable({ gaps }: GapTableProps) {
  const columns: TableProps<GapItem>['columns'] = [
    {
      title: '技能名称',
      dataIndex: 'skill',
      key: 'skill',
      render: (text: string) => <span style={{ fontWeight: 600 }}>{text}</span>,
    },
    {
      title: '权重',
      dataIndex: 'weight',
      key: 'weight',
      width: 140,
      render: (weight: GapItem['weight']) => {
        const wm = weightMap[weight] ?? WEIGHT_UNKNOWN;
        return (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ flex: 1 }}>
              <MiniBar value={wm.value} showValue={false} />
            </div>
            <span style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-secondary)', width: 16 }}>{wm.label}</span>
          </div>
        );
      },
    },
    {
      title: '当前状态',
      dataIndex: 'status',
      key: 'status',
      width: 120,
      render: (status: GapItem['status']) => {
        const sm = statusMap[status] ?? STATUS_UNKNOWN;
        return <SemanticTag semantic={sm.semantic}>{sm.label}</SemanticTag>;
      },
    },
    {
      title: 'JD 要求（来源）',
      dataIndex: 'jdSource',
      key: 'jdSource',
      render: (text: string, record: GapItem) => (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
          <span style={{ color: 'var(--color-text-secondary)' }}>{text || '—'}</span>
          <DataGradeBadge grade={record.dataGrade} />
        </div>
      ),
    },
    {
      title: '判定依据（证据）',
      dataIndex: 'evidence',
      key: 'evidence',
      render: (text: string) => <span style={{ color: 'var(--color-text-primary)' }}>{text || '—'}</span>,
    },
  ];

  return (
    <div style={{ overflowX: 'auto' }}>
      <Table<GapItem>
        rowKey="skill"
        columns={columns}
        dataSource={gaps}
        pagination={false}
        size="middle"
        style={{ borderRadius: 'var(--radius-sm)' }}
        components={{
          header: {
            cell: (props: React.ComponentProps<'th'>) => (
              <th {...props} style={{ background: 'var(--color-bg-subtle)', ...props.style }} />
            ),
          },
        }}
      />
    </div>
  );
}
