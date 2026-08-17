/* C-09 步骤条 Stepper：报告流 4 步（画像 → 方向 → 差距 → 计划）
   完成步可回跳；移动端收窄为「第 N 步 / 共 4 步」 */
import { Steps } from 'antd';

const STEPS = ['职业画像', '方向推荐', '差距分析', '成长计划'];

interface ReportStepperProps {
  current: number; // 0-based 当前步
  onStepClick?: (step: number) => void;
  /** ：聚合页模式所有步骤可点击（含当前步 index===current）；三步页不传行为不变 */
  allClickable?: boolean;
}

export default function ReportStepper({ current, onStepClick, allClickable }: ReportStepperProps) {
  return (
    <div style={{ height: 56, display: 'flex', alignItems: 'center' }}>
      <Steps
        current={current}
        size="small"
        responsive
        className="report-stepper"
        items={STEPS.map((title, index) => ({
          title,
          onClick: onStepClick && (index < current || allClickable) ? () => onStepClick(index) : undefined,
          style: onStepClick && (index < current || allClickable) ? { cursor: 'pointer' } : undefined,
        }))}
      />
    </div>
  );
}
