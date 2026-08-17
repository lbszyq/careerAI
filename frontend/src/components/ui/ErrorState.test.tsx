import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import ErrorState from './ErrorState';

describe('ErrorState 错误状态组件', () => {
  it('错误态渲染：显示标题、描述与重试/返回入口（异常）', () => {
    render(
      <ErrorState title="加载失败" description="服务暂时不可用" onRetry={() => {}} onBack={() => {}} />,
    );

    expect(screen.getByText('加载失败')).toBeInTheDocument();
    expect(screen.getByText('服务暂时不可用')).toBeInTheDocument();
    // antd 会对两个汉字按钮自动插入空格，使用正则匹配可访问名称
    expect(screen.getByRole('button', { name: /重\s*试/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /返\s*回/ })).toBeInTheDocument();
  });

  it('点击重试按钮触发 onRetry 回调', async () => {
    const onRetry = vi.fn();
    render(<ErrorState title="加载失败" onRetry={onRetry} />);

    await userEvent.click(screen.getByRole('button', { name: /重\s*试/ }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('不传任何回调时不渲染操作按钮（边界）', () => {
    render(<ErrorState title="加载失败" />);

    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });
});
