'use client';

import React, { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';

interface LineChartProps {
  data: Array<{ date: string; value: number; benchmark?: number }>;
  height?: number;
  title?: string;
  showLegend?: boolean;
}

export function LineChart({ data, height = 300, title, showLegend = true }: LineChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!chartRef.current) return;

    // 初始化图表
    if (!chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current);
    }

    const option: EChartsOption = {
      title: title ? { text: title, left: 'center' } : undefined,
      tooltip: {
        trigger: 'axis',
        axisPointer: {
          type: 'cross',
        },
      },
      legend: showLegend
        ? {
            data: ['策略收益', '基准收益'],
            top: title ? 30 : 10,
          }
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
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          formatter: (value: number) => `${value.toFixed(2)}%`,
        },
      },
      series: [
        {
          name: '策略收益',
          type: 'line',
          data: data.map((item) => item.value),
          smooth: true,
          itemStyle: {
            color: '#3b82f6',
          },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(59, 130, 246, 0.3)' },
                { offset: 1, color: 'rgba(59, 130, 246, 0.05)' },
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
                itemStyle: {
                  color: '#94a3b8',
                },
                lineStyle: {
                  type: 'dashed' as const,
                },
              },
            ]
          : []),
      ],
    };

    chartInstance.current.setOption(option);

    // 响应式调整
    const handleResize = () => {
      chartInstance.current?.resize();
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chartInstance.current?.dispose();
    };
  }, [data, height, title, showLegend]);

  return <div ref={chartRef} style={{ width: '100%', height: `${height}px` }} />;
}


