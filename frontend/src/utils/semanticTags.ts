/* 语义标签映射纯函数（：从 SemanticTag.tsx 拆出，消除组件文件混合非组件导出触发的 react-refresh 警告） */
export type TagSemantic = 'success' | 'warning' | 'danger' | 'info';

/** 需求趋势 / 竞争热度 → 语义映射 */
export function trendSemantic(trend: 'growth' | 'stable' | 'decline'): TagSemantic {
  if (trend === 'growth') return 'success';
  if (trend === 'stable') return 'warning';
  return 'danger';
}

export function heatSemantic(heat: 'high' | 'medium' | 'low'): TagSemantic {
  if (heat === 'high') return 'danger';
  if (heat === 'medium') return 'warning';
  return 'success';
}
