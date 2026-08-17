import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import EmptyState from './EmptyState';

describe('EmptyState 空状态组件', () => {
  it('空数据渲染：显示标题与描述（边界）', () => {
    render(<EmptyState title="暂无报告" description="完成一次评估后即可查看" />);

    expect(screen.getByText('暂无报告')).toBeInTheDocument();
    expect(screen.getByText('完成一次评估后即可查看')).toBeInTheDocument();
  });

  it('不传 actionText/onAction 时不渲染操作按钮（边界）', () => {
    render(<EmptyState title="暂无数据" />);

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('点击操作按钮触发 onAction 回调', async () => {
    const onAction = vi.fn();
    render(<EmptyState title="暂无数据" actionText="去生成" onAction={onAction} />);

    await userEvent.click(screen.getByRole('button', { name: '去生成' }));

    expect(onAction).toHaveBeenCalledTimes(1);
  });
});
