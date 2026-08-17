/* C-23 雷达图 RadarChart（能力五维度）
   规格：480×360；五轴 0-100；顶点显示数值；填充 rgba(44,74,110,.15) + primary-600 描边 */
import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import EChart from '../ui/EChart';
import type { AbilityDimension } from '../../types';

interface RadarChartProps {
  dimensions: AbilityDimension[];
  height?: number;
  minHeight?: number;
}

export default function RadarChart({ dimensions, height = 360, minHeight = 300 }: RadarChartProps) {
  const option = useMemo<EChartsOption | null>(() => {
    // 核心防御：过滤空/异常维度，无有效项时不渲染 EChart（禁止空 indicator 进 ECharts）
    const valid = dimensions.filter((d) => d && d.name && typeof d.score === 'number' && Number.isFinite(d.score));
    if (valid.length === 0) return null;
    const indicators = valid.map((d) => ({ name: d.name, max: 100 }));
    const values = valid.map((d) => d.score);
    return {
      tooltip: {
        trigger: 'item',
        formatter: (params: unknown) => {
          const p = params as { name?: string; value?: number };
          return `${p.name ?? ''}：${p.value ?? 0} 分`;
        },
      },
      radar: {
        indicator: indicators,
        radius: '68%',
        splitArea: { areaStyle: { color: ['rgba(242,246,250,0.4)', 'rgba(227,235,243,0.4)'] } },
        axisLine: { lineStyle: { color: '#D2C9BC' } },
        splitLine: { lineStyle: { color: '#E2DCD2' } },
        axisName: { color: '#4A5560', fontSize: 13 },
      },
      series: [
        {
          type: 'radar',
          data: [
            {
              value: values,
              name: '用户',
              areaStyle: { color: 'rgba(44,74,110,0.15)' },
              lineStyle: { color: '#2C4A6E', width: 2 },
              itemStyle: { color: '#2C4A6E' },
              label: { show: true, fontSize: 12, fontWeight: 700, color: '#232A33', formatter: (p: unknown) => String((p as { value?: number }).value ?? '') },
            },
          ],
        },
      ],
    };
  }, [dimensions]);

  if (!option) return null;
  return <EChart option={option} height={height} minHeight={minHeight} ariaLabel="能力五维雷达图" />;
}
