/* C-24 箱线图 BoxplotChart（薪资分布）
   规格：480×260；标注 P25/P50/P75 数值；单位 k/月；
   样式：primary-100 填充 + primary-600 描边，中位数线 accent-600 */
import { useMemo } from 'react';
import type { EChartsOption } from 'echarts';
import EChart from '../ui/EChart';

export interface BoxplotData {
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

interface BoxplotChartProps {
  data: BoxplotData;
  name?: string;
  height?: number;
}

export default function BoxplotChart({ data, name = '薪资分布', height = 260 }: BoxplotChartProps) {
  const option = useMemo<EChartsOption>(() => {
    const box = [data.min, data.q1, data.median, data.q3, data.max];
    return {
      tooltip: {
        trigger: 'item',
        formatter: () =>
          `P25：${data.q1}k/月<br/>P50（中位数）：${data.median}k/月<br/>P75：${data.q3}k/月<br/>范围：${data.min} - ${data.max}k/月`,
      },
      grid: { left: 40, right: 16, top: 24, bottom: 32 },
      xAxis: {
        type: 'category',
        data: [name],
        axisLabel: { color: '#4A5560' },
        axisLine: { lineStyle: { color: '#D2C9BC' } },
        axisTick: { lineStyle: { color: '#D2C9BC' } },
      },
      yAxis: {
        type: 'value',
        name: 'k/月',
        nameTextStyle: { color: '#8A94A0' },
        axisLabel: { color: '#4A5560' },
        axisLine: { lineStyle: { color: '#D2C9BC' } },
        splitLine: { lineStyle: { color: '#EDE7DE' } },
      },
      series: [
        {
          type: 'boxplot',
          data: [box],
          itemStyle: { color: '#E3EBF3', borderColor: '#2C4A6E', borderWidth: 2 },
        },
      ],
      // 用 markLine 标注 P25/P50/P75 数值（颜色 + 数值双编码）
      graphic: [
        { type: 'text', right: 8, top: 8, style: { text: 'P25 ' + data.q1, fill: '#4A5560', fontSize: 12 } },
        { type: 'text', right: 8, top: 40, style: { text: 'P50 ' + data.median, fill: '#A8762F', fontSize: 12, fontWeight: 600 } },
        { type: 'text', right: 8, top: 72, style: { text: 'P75 ' + data.q3, fill: '#4A5560', fontSize: 12 } },
      ],
    };
  }, [data, name]);

  return <EChart option={option} height={height} minHeight={220} ariaLabel="薪资分布箱线图" />;
}
