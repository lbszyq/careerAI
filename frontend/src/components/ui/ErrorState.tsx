/* C-15 错误状态 ErrorState：Result 样式，可恢复出口 */
import { Button, Result } from 'antd';

interface ErrorStateProps {
  title: string;
  description?: string;
  onRetry?: () => void;
  onBack?: () => void;
}

export default function ErrorState({ title, description, onRetry, onBack }: ErrorStateProps) {
  return (
    <Result
      status="error"
      title={title}
      subTitle={description}
      extra={[
        onRetry && (
          <Button type="primary" key="retry" onClick={onRetry}>
            重试
          </Button>
        ),
        onBack && (
          <Button key="back" onClick={onBack}>
            返回
          </Button>
        ),
      ].filter(Boolean)}
    />
  );
}
