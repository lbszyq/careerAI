/* C-33 生成进度 GenProgress（页面级）
   步骤清单（图标 + 名称 + 三态）+ 进度环 + 小贴士轮播 + 计时
   阶段一：步骤推进由父级模拟驱动（mock），阶段二接轮询 */
import { CheckCircleFilled, LoadingOutlined, ArrowUpOutlined } from '@ant-design/icons';
import { Progress, Alert, Button } from 'antd';
import { useEffect, useState } from 'react';
import AIGeneratedTag from './AIGeneratedTag';

/* 当前步骤呼吸动画（交互规范 ：仅生成中当前步骤允许） */
const breatheKeyframes = `
@keyframes careerai-breathe {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
`;

export type GenStepState = 'pending' | 'running' | 'done';

export interface GenStep {
  name: string;
  state: GenStepState;
}

interface GenProgressProps {
  title: string;
  subtitle?: string;
  steps: GenStep[];
  percent: number;
  tips: string[];
  elapsedSeconds: number;
  remainingSeconds: number;
  timeoutAlert?: boolean;
  onContinueWait?: () => void;
  onCancel?: () => void;
  onLeave?: () => void;
}

export default function GenProgress({
  title,
  subtitle,
  steps,
  percent,
  tips,
  elapsedSeconds,
  remainingSeconds,
  timeoutAlert,
  onContinueWait,
  onCancel,
  onLeave,
}: GenProgressProps) {
  const [tipIndex, setTipIndex] = useState(0);

  // 小贴士轮播：8s 切换
  useEffect(() => {
    if (tips.length <= 1) return;
    const timer = window.setInterval(() => {
      setTipIndex((prev) => (prev + 1) % tips.length);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [tips.length]);

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m} 分 ${sec.toString().padStart(2, '0')} 秒`;
  };

  return (
    <div style={{ maxWidth: 720, margin: '0 auto', textAlign: 'center' }}>
      <style>{breatheKeyframes}</style>
      {/* 标题区 */}
      <div style={{ marginBottom: 'var(--space-6)' }}>
        <h1 style={{ fontSize: 'var(--font-size-2xl)', fontWeight: 600, margin: 0 }}>{title}</h1>
        <div style={{ marginTop: 'var(--space-2)', display: 'flex', justifyContent: 'center', gap: 8, alignItems: 'center' }}>
          <AIGeneratedTag />
          <span style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-secondary)' }}>
            {subtitle ?? '预计 2 分钟，完成自动展示报告'}
          </span>
        </div>
      </div>

      {/* 超时提示 */}
      {timeoutAlert && (
        <Alert
          type="warning"
          showIcon
          message="分析时间比预期长，请稍候"
          action={
            <div style={{ display: 'flex', gap: 8 }}>
              <Button size="small" type="primary" onClick={onContinueWait}>继续等待</Button>
              <Button size="small" onClick={onCancel}>取消生成</Button>
            </div>
          }
          style={{ marginBottom: 'var(--space-6)', textAlign: 'left' }}
        />
      )}

      {/* 步骤清单 */}
      <div style={{ textAlign: 'left', marginBottom: 'var(--space-8)' }}>
        <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
          {steps.map((step) => (
            <li
              key={step.name}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 'var(--space-3)',
                padding: 'var(--space-3) 0',
                borderBottom: '1px solid var(--color-divider)',
              }}
            >
              {step.state === 'done' && <CheckCircleFilled style={{ fontSize: 32, color: 'var(--color-success-600)' }} aria-label="已完成" />}
              {step.state === 'running' && (
                <span
                  aria-label="进行中"
                  style={{
                    width: 32,
                    height: 32,
                    borderRadius: '50%',
                    border: '2px solid var(--color-primary-600)',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    animation: 'careerai-breathe 2s ease-in-out infinite',
                  }}
                >
                  <LoadingOutlined style={{ color: 'var(--color-primary-600)' }} />
                </span>
              )}
              {step.state === 'pending' && (
                <span
                  aria-label="待处理"
                  style={{ width: 32, height: 32, borderRadius: '50%', border: '2px solid var(--color-border-strong)', display: 'inline-block' }}
                />
              )}
              <span
                style={{
                  fontSize: 'var(--font-size-base)',
                  fontWeight: step.state === 'running' ? 600 : 400,
                  color: step.state === 'pending' ? 'var(--color-text-tertiary)' : 'var(--color-text-primary)',
                }}
              >
                {step.name}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {/* 进度环 */}
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 'var(--space-8)' }}>
        <Progress
          type="circle"
          percent={percent}
          size={96}
          strokeWidth={10}
          strokeColor="var(--color-success-600)"
          trailColor="var(--color-border-default)"
          format={() => <span className="tnum" style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600 }}>{percent}%</span>}
        />
      </div>

      {/* 小贴士轮播 */}
      <div
        aria-live="polite"
        style={{
          maxWidth: 480,
          margin: '0 auto var(--space-6)',
          padding: 'var(--space-3) var(--space-4)',
          background: 'var(--color-bg-subtle)',
          borderRadius: 'var(--radius-md)',
          fontSize: 'var(--font-size-sm)',
          color: 'var(--color-text-secondary)',
          minHeight: 44,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {tips[tipIndex] ?? ''}
      </div>

      {/* 底部：已用 / 剩余 + 离开 */}
      <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-tertiary)', display: 'flex', justifyContent: 'center', gap: 'var(--space-6)' }}>
        <span>已用时间：{formatTime(elapsedSeconds)}</span>
        <span>预计剩余：{formatTime(remainingSeconds)}</span>
      </div>
      {onLeave && (
        <div style={{ marginTop: 'var(--space-4)' }}>
          <Button type="link" onClick={onLeave}>
            <ArrowUpOutlined /> 离开页面（生成结果将保存到「我的报告」，不取消生成）
          </Button>
        </div>
      )}
    </div>
  );
}
