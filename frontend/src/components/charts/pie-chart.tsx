'use client';

import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';
import { useThemeStore } from '@/stores/useThemeStore';
import { getChartPalette } from './chart-theme';

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

  return <div ref={chartRef} style={{ width: '100%', height: `${height}px` }} />;
}
