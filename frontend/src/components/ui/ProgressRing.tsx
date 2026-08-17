/* C-18 进度环 ProgressRing：antd Progress circle 定制 */
import { Progress } from 'antd';

interface ProgressRingProps {
  percent: number;
  size?: number;
  text?: string;
}

export default function ProgressRing({ percent, size = 120, text }: ProgressRingProps) {
  return (
    <Progress
      type="circle"
      percent={percent}
      size={size}
      strokeWidth={10}
      strokeColor="var(--color-success-600)"
      trailColor="var(--color-border-default)"
      format={() => <span className="tnum" style={{ fontSize: 'var(--font-size-xl)', fontWeight: 600 }}>{text ?? `${percent}%`}</span>}
    />
  );
}
