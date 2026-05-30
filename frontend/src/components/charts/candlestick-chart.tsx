'use client';

import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import type { EChartsOption } from 'echarts';
import type { KlineData } from '@/lib/api/market';
import { boll, kdj, ma, macd, rsi } from '@/lib/utils/indicators';

export type MainOverlay = 'ma' | 'boll' | 'none';
export type SubIndicator = 'macd' | 'kdj' | 'rsi' | 'none';

interface CandlestickChartProps {
  data: KlineData[];
  height?: number;
  overlay?: MainOverlay;
  sub?: SubIndicator;
}

// A 股惯例：红涨绿跌
const UP = '#e23b3b';
const DOWN = '#16a34a';
const MA_COLORS: Record<number, string> = {
  5: '#f59e0b',
  10: '#3b82f6',
  20: '#a855f7',
  60: '#64748b',
};

function nz(v: number | null): number | string {
  return v === null ? '-' : v;
}

export function CandlestickChart({
  data,
  height = 460,
  overlay = 'ma',
  sub = 'macd',
}: CandlestickChartProps) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    if (!chart.current) chart.current = echarts.init(ref.current);

    const dates = data.map((d) => d.time);
    const candles = data.map((d) => [d.open, d.close, d.low, d.high]);
    const closes = data.map((d) => d.close);
    const highs = data.map((d) => d.high);
    const lows = data.map((d) => d.low);
    const vols = data.map((d, i) => ({
      value: d.volume,
      itemStyle: { color: d.close >= d.open ? UP : DOWN },
      idx: i,
    }));

    const hasSub = sub !== 'none';
    // 网格高度分配
    const mainTop = 8;
    const mainHeight = hasSub ? 50 : 62;
    const volTop = mainTop + mainHeight + 4;
    const volHeight = hasSub ? 14 : 22;
    const subTop = volTop + volHeight + 5;
    const subHeight = 18;

    const grids: NonNullable<EChartsOption['grid']> = [
      { left: 52, right: 16, top: `${mainTop}%`, height: `${mainHeight}%` },
      { left: 52, right: 16, top: `${volTop}%`, height: `${volHeight}%` },
    ];
    if (hasSub) grids.push({ left: 52, right: 16, top: `${subTop}%`, height: `${subHeight}%` });

    const xAxes: NonNullable<EChartsOption['xAxis']> = [
      { type: 'category', data: dates, gridIndex: 0, boundaryGap: true, axisLine: { lineStyle: { color: '#888' } }, axisLabel: { show: false }, axisPointer: { label: { show: true } } },
      { type: 'category', data: dates, gridIndex: 1, boundaryGap: true, axisLabel: { show: !hasSub }, axisLine: { lineStyle: { color: '#888' } } },
    ];
    if (hasSub) {
      xAxes.push({ type: 'category', data: dates, gridIndex: 2, boundaryGap: true, axisLabel: { show: true }, axisLine: { lineStyle: { color: '#888' } } });
    }

    const yAxes: NonNullable<EChartsOption['yAxis']> = [
      { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: 'rgba(128,128,128,0.12)' } }, axisLabel: { color: '#888' } },
      { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
    ];
    if (hasSub) {
      yAxes.push({ scale: true, gridIndex: 2, splitNumber: 2, axisLabel: { color: '#888' }, splitLine: { show: false } });
    }

    type SeriesOption = NonNullable<EChartsOption['series']>;
    const series = [
      {
        name: 'K线',
        type: 'candlestick',
        data: candles,
        xAxisIndex: 0,
        yAxisIndex: 0,
        itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
      },
      {
        name: '成交量',
        type: 'bar',
        data: vols,
        xAxisIndex: 1,
        yAxisIndex: 1,
      },
    ] as unknown[] as SeriesOption;

    const sArr = series as unknown[];

    if (overlay === 'ma') {
      [5, 10, 20, 60].forEach((p) => {
        sArr.push({
          name: `MA${p}`,
          type: 'line',
          data: ma(closes, p).map(nz),
          xAxisIndex: 0,
          yAxisIndex: 0,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1, color: MA_COLORS[p] },
        });
      });
    } else if (overlay === 'boll') {
      const b = boll(closes, 20, 2);
      const lines: [string, typeof b.mid, string][] = [
        ['BOLL中轨', b.mid, '#3b82f6'],
        ['BOLL上轨', b.upper, '#f59e0b'],
        ['BOLL下轨', b.lower, '#a855f7'],
      ];
      lines.forEach(([name, vals, color]) => {
        sArr.push({
          name,
          type: 'line',
          data: vals.map(nz),
          xAxisIndex: 0,
          yAxisIndex: 0,
          smooth: true,
          showSymbol: false,
          lineStyle: { width: 1, color },
        });
      });
    }

    if (sub === 'macd') {
      const m = macd(closes);
      sArr.push({
        name: 'MACD',
        type: 'bar',
        data: m.hist.map((v) => ({ value: v, itemStyle: { color: v >= 0 ? UP : DOWN } })),
        xAxisIndex: 2,
        yAxisIndex: 2,
      });
      sArr.push({ name: 'DIF', type: 'line', data: m.dif, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } });
      sArr.push({ name: 'DEA', type: 'line', data: m.dea, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#3b82f6' } });
    } else if (sub === 'kdj') {
      const k = kdj(highs, lows, closes);
      sArr.push({ name: 'K', type: 'line', data: k.k, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } });
      sArr.push({ name: 'D', type: 'line', data: k.d, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#3b82f6' } });
      sArr.push({ name: 'J', type: 'line', data: k.j, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#a855f7' } });
    } else if (sub === 'rsi') {
      sArr.push({ name: 'RSI6', type: 'line', data: rsi(closes, 6).map(nz), xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#f59e0b' } });
      sArr.push({ name: 'RSI12', type: 'line', data: rsi(closes, 12).map(nz), xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#3b82f6' } });
    }

    const zoomXAxisIndex = hasSub ? [0, 1, 2] : [0, 1];
    const option: EChartsOption = {
      animation: false,
      legend: {
        top: 0,
        type: 'scroll',
        textStyle: { color: '#888', fontSize: 11 },
        itemWidth: 14,
        itemHeight: 8,
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        confine: true,
        backgroundColor: 'rgba(20,20,22,0.92)',
        borderColor: 'rgba(255,255,255,0.1)',
        textStyle: { color: '#eee', fontSize: 12 },
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: grids,
      xAxis: xAxes,
      yAxis: yAxes,
      dataZoom: [
        { type: 'inside', xAxisIndex: zoomXAxisIndex, start: Math.max(0, 100 - (60 / Math.max(dates.length, 1)) * 100), end: 100 },
        { type: 'slider', xAxisIndex: zoomXAxisIndex, height: 16, bottom: 4, start: 60, end: 100 },
      ],
      series,
    };

    chart.current.setOption(option, { notMerge: true });

    const onResize = () => chart.current?.resize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [data, overlay, sub, height]);

  useEffect(() => {
    return () => {
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  return <div ref={ref} style={{ width: '100%', height: `${height}px` }} />;
}
