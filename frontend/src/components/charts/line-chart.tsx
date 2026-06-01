'use client';

import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';
import { useThemeStore } from '@/stores/useThemeStore';
import { getChartPalette, withAlpha } from './chart-theme';

interface LineChartProps {
  data: Array<{ date: string; value: number; benchmark?: number }>;
  height?: number;
  title?: string;
  showLegend?: boolean;
}

export function LineChart({ data, height = 300, title, showLegend = true }: LineChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);
  const theme = useThemeStore((s) => s.theme);

  // 初始化（懒）+ 数据/主题变化时 setOption；不在数据变化时 dispose（避免重建）
  useEffect(() => {
    if (!chartRef.current) return;
    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current);
    }
    const c = getChartPalette();

    const option: EChartsOption = {
      title: title ? { text: title, left: 'center', textStyle: { color: c.foreground } } : undefined,
      tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
      legend: showLegend
        ? { data: ['策略收益', '基准收益'], top: title ? 30 : 10, textStyle: { color: c.muted } }
        : undefined,
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        top: title ? (showLegend ? 60 : 40) : showLegend ? 40 : 20,
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        boundaryGap: false,
        data: data.map((item) => item.date),
        axisLine: { lineStyle: { color: c.border } },
        axisLabel: { color: c.muted },
      },
      yAxis: {
        type: 'value',
        axisLabel: { color: c.muted, formatter: (value: number) => `${value.toFixed(2)}%` },
        splitLine: { lineStyle: { color: withAlpha(c.muted, 0.15) } },
      },
      series: [
        {
          name: '策略收益',
          type: 'line',
          data: data.map((item) => item.value),
          smooth: true,
          showSymbol: false,
          itemStyle: { color: c.brand },
          lineStyle: { color: c.brand },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: withAlpha(c.brand, 0.28) },
                { offset: 1, color: withAlpha(c.brand, 0.04) },
              ],
            },
          },
        },
        ...(data[0]?.benchmark !== undefined
          ? [
              {
                name: '基准收益',
                type: 'line' as const,
                data: data.map((item) => item.benchmark ?? 0),
                smooth: true,
                showSymbol: false,
                itemStyle: { color: c.muted },
                lineStyle: { color: c.muted, type: 'dashed' as const },
              },
            ]
          : []),
      ],
    };

    chartInstance.current.setOption(option, { notMerge: true });

    const handleResize = () => chartInstance.current?.resize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [data, height, title, showLegend, theme]);

  // 仅卸载时销毁
  useEffect(() => {
    return () => {
      chartInstance.current?.dispose();
      chartInstance.current = null;
    };
  }, []);

  return <div ref={chartRef} style={{ width: '100%', height: `${height}px` }} />;
}
