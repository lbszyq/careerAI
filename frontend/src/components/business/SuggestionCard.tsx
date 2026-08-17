/* v1.1 AI 策略建议卡：后标题移至页面级 h2，对齐报告页「h2+卡」结构
   结构=一句话结论 → 为什么 → 适用条件 → 查看完整分析；证据（画像/方向/差距）为主体
   无 suggestion（Stage 1 未选方向/生成失败/存量报告）→ 整卡不渲染（由页面判断，本组件同样兜底） */
import { Card, Button } from 'antd';
import type { ApiSuggestion } from '../../types';

interface SuggestionCardProps {
  suggestion?: ApiSuggestion | null;
  onViewFullAnalysis: () => void;
}

export default function SuggestionCard({ suggestion, onViewFullAnalysis }: SuggestionCardProps) {
  const reasons = Array.isArray(suggestion?.reasons) ? suggestion.reasons : [];
  const hasContent = Boolean(suggestion && (suggestion.summary || reasons.length > 0 || suggestion.applicable_condition));
  if (!hasContent) return null;
  return (
    <Card
      style={{ borderRadius: 'var(--radius-md)' }}
      styles={{ body: { padding: 'var(--space-6)' } }}
    >
      {suggestion?.summary && (
        <div style={{ fontSize: 'var(--font-size-base)', fontWeight: 600, lineHeight: '24px', marginBottom: 'var(--space-3)' }}>
          {suggestion.summary}
        </div>
      )}
      {reasons.length > 0 && (
        <div style={{ marginBottom: 'var(--space-3)' }}>
          <div style={{ fontSize: 'var(--font-size-xs)', fontWeight: 600, color: 'var(--color-text-secondary)', marginBottom: 4 }}>为什么</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {reasons.map((text, i) => (
              <div key={i} style={{ display: 'flex', gap: 6, fontSize: 'var(--font-size-sm)', lineHeight: '20px' }}>
                <span style={{ color: 'var(--color-primary-500)', flexShrink: 0 }}>·</span>
                <span>{text}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      {suggestion?.applicable_condition && (
        <div style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)', marginBottom: 'var(--space-3)' }}>
          <span style={{ fontWeight: 600 }}>适用条件：</span>
          {suggestion.applicable_condition}
        </div>
      )}
      <div style={{ textAlign: 'right' }}>
        <Button type="link" size="small" onClick={onViewFullAnalysis} style={{ padding: 0, height: 'auto' }}>
          查看完整分析 ↓
        </Button>
      </div>
    </Card>
  );
}
