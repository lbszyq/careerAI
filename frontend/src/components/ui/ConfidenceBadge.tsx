/* C-21 置信度标注 ConfidenceBadge：低/中置信度时标注 */
import { Tooltip } from 'antd';
import { InfoCircleOutlined } from '@ant-design/icons';
import SemanticTag from './SemanticTag';
import type { TagSemantic } from '../../utils/semanticTags';

interface ConfidenceBadgeProps {
  level: 'high' | 'medium' | 'low';
  note?: string;
}

const levelText: Record<string, string> = {
  high: '高置信度',
  medium: '中置信度',
  low: '低置信度',
};

export default function ConfidenceBadge({ level, note }: ConfidenceBadgeProps) {
  if (level === 'high') return null;
  const semantic: TagSemantic = level === 'low' ? 'warning' : 'info';
  return (
    <Tooltip title={note ?? '该结果基于较少数据或模糊信息，建议补充资料后重新生成'}>
      <span>
        <SemanticTag semantic={semantic} icon={<InfoCircleOutlined style={{ marginRight: 4 }} />}>
          {levelText[level]}
        </SemanticTag>
      </span>
    </Tooltip>
  );
}
