'use client';

import { useEffect, useRef } from 'react';
import * as echarts from 'echarts/core';
import { PieChart as EPieChart } from 'echarts/charts';
import {
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import type { EChartsOption } from 'echarts';
import { useThemeStore } from '@/stores/useThemeStore';
import { getChartPalette } from './chart-theme';

echarts.use([EPieChart, TooltipComponent, LegendComponent, TitleComponent, CanvasRenderer]);

interface PieChartData {
  name: string;
  value: number;
}

interface PieChartProps {
  data: PieChartData[];
  height?: number;
  title?: string;
}

export function PieChart({ data, height = 300, title }: PieChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const theme = useThemeStore((s) => s.theme);

  useEffect(() => {
    if (!chartRef.current) return;
    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current);
    }
    const c = getChartPalette();

    const option: EChartsOption = {
      color: c.series,
      title: title ? { text: title, left: 'center', textStyle: { color: c.foreground } } : undefined,
      tooltip: { trigger: 'item', formatter: '{a} <br/>{b}: ¥{c} ({d}%)' },
      legend: {
        orient: 'vertical',
        left: 'left',
        top: title ? 50 : 20,
        textStyle: { color: c.muted },
      },
      series: [
        {
          name: '持仓分布',
          type: 'pie',
          radius: ['40%', '70%'],
          avoidLabelOverlap: false,
          // 切片描边用卡片底色，明暗主题下都能清晰分隔（原先硬编码 #fff 在暗色下突兀）
          itemStyle: { borderRadius: 10, borderColor: c.card, borderWidth: 2 },
          label: { show: false, position: 'center', color: c.foreground },
          emphasis: { label: { show: true, fontSize: 20, fontWeight: 'bold', color: c.foreground } },
          labelLine: { show: false },
          data,
        },
      ],
    };

    chartInstance.current.setOption(option, { notMerge: true });

    const handleResize = () => chartInstance.current?.resize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [data, height, title, theme]);

  useEffect(() => {
    return () => {
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  const topSlice = data.length > 0 ? [...data].sort((a, b) => b.value - a.value)[0] : null;
  const chartLabel = `饼图，${data.length} 个分类${topSlice ? `，最大项 ${topSlice.name}` : ''}${title ? `，${title}` : ''}`;

  return (
    <div role="img" aria-label={chartLabel}>
      <div ref={chartRef} style={{ width: '100%', height: `${height}px` }} />
      <span className="sr-only">{chartLabel}</span>
    </div>
  );
}
