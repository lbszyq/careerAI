/* ECharts 通用 React 封装（图表统一入口）
   图表通用要求：tooltip 显示数值；reduced-motion 禁用动画；容器 min-height 稳定
    性能优化：改用 echarts/core 按需注册，仅打包本项目用到的图表，避免全量 echarts（约 1MB）进入首屏
    精简：移除未使用的 Bar/Line 图与 Legend/Title 组件（项目实际仅用雷达图/箱线图），缩小 echarts chunk */
import { useEffect, useRef } from 'react';
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core';
import { RadarChart, BoxplotChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  GraphicComponent,
  RadarComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

use([
  RadarChart,
  BoxplotChart,
  GridComponent,
  TooltipComponent,
  GraphicComponent,
  RadarComponent,
  CanvasRenderer,
]);

interface EChartProps {
  option: EChartsCoreOption;
  height?: number;
  minHeight?: number;
  ariaLabel?: string;
}

export default function EChart({ option, height, minHeight = 240, ariaLabel }: EChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = init(containerRef.current);
    chartRef.current = chart;

    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const finalOption = reduced ? { ...option, animation: false } : option;
    chartRef.current?.setOption(finalOption, true);
  }, [option]);

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={ariaLabel ?? '数据图表'}
      style={{ width: '100%', height: height ?? minHeight, minHeight }}
    />
  );
}
