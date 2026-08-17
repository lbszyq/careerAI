/* ：任务“已由成果覆盖”标签
   标准 1：covered_by_achievement=true → 渲染「已由成果覆盖」标签
   标准 2：false / undefined → 不渲染该标签；组件不抛异常 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import TaskItem from './TaskItem';
import type { PlanTask } from '../../types';

const baseTask: PlanTask = {
  id: 't1',
  name: '完成机器学习课程',
  resource: 'Coursera',
  duration: '2 周',
  stage: 'short',
  status: 'pending',
};

describe('TaskItem 成果覆盖标签', () => {
  it('标准 1：covered_by_achievement=true 时渲染「已由成果覆盖」标签', () => {
    render(<TaskItem task={{ ...baseTask, coveredByAchievement: true }} />);

    expect(screen.getByText('已由成果覆盖')).toBeInTheDocument();
    expect(screen.getByText('未开始')).toBeInTheDocument();
  });

  it('标准 2：covered_by_achievement=false 时不渲染覆盖标签', () => {
    render(<TaskItem task={{ ...baseTask, coveredByAchievement: false }} />);

    expect(screen.queryByText('已由成果覆盖')).not.toBeInTheDocument();
    expect(screen.getByText('未开始')).toBeInTheDocument();
  });

  it('标准 2：covered_by_achievement=undefined（存量计划）不渲染覆盖标签且不抛异常', () => {
    render(<TaskItem task={baseTask} />);

    expect(screen.queryByText('已由成果覆盖')).not.toBeInTheDocument();
    expect(screen.getByText('未开始')).toBeInTheDocument();
  });

  it('已覆盖且已完成时两个标签同时存在', () => {
    render(<TaskItem task={{ ...baseTask, status: 'done', coveredByAchievement: true }} />);

    expect(screen.getByText('已由成果覆盖')).toBeInTheDocument();
    expect(screen.getByText('已完成')).toBeInTheDocument();
  });
});
