/* v1.1 市场数据来源等级徽标 DataGradeBadge
   等级=来源可信度（A 官方统计 / B 公开招聘数据 / C AI 推断），不代表推荐正确率；
   语义说明挂 Tooltip，避免误导性解读；缺失/非法等级不渲染（优雅降级） */
import { Tooltip } from 'antd';
import SemanticTag from './SemanticTag';
import type { TagSemantic } from '../../utils/semanticTags';

interface DataGradeMeta {
  semantic: TagSemantic;
  label: string;
  desc: string;
}

const GRADE_META: Record<string, DataGradeMeta> = {
  A: { semantic: 'success', label: 'A 官方统计', desc: '政府/权威机构发布的统计数据' },
  B: { semantic: 'info', label: 'B 公开招聘', desc: '招聘平台/公开招聘信息聚合' },
  C: { semantic: 'warning', label: 'C AI 推断', desc: '无结构化数据源，AI 基于公开信息推断' },
};

interface DataGradeBadgeProps {
  grade?: string | null;
}

export default function DataGradeBadge({ grade }: DataGradeBadgeProps) {
  if (!grade) return null;
  const meta = GRADE_META[grade.toUpperCase()];
  if (!meta) return null;
  return (
    <Tooltip title={`市场数据来源等级：${meta.label}（${meta.desc}）——来源可信度，不代表推荐正确率`}>
      <span>
        <SemanticTag semantic={meta.semantic}>{meta.label}</SemanticTag>
      </span>
    </Tooltip>
  );
}
