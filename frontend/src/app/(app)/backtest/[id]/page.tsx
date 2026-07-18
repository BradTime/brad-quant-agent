'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { ArrowLeft, FlaskConical, Loader2 } from 'lucide-react';
import { Markdown } from '@/components/ai/markdown';
import { LineChart } from '@/components/charts';
import {
  backtestApi,
  streamBacktestReview,
  type BacktestRunResult,
} from '@/lib/api/backtest';
import { formatBacktestTime } from '@/lib/utils/format';
import { ERROR_CODES } from '@/lib/constants';
import type { ApiResponse } from '@/types';
import { DataQualityNotice } from '../page';

const ENGINES: Record<string, string> = {
  native: 'Native（自研）',
  backtrader: 'Backtrader',
};

const FREQUENCIES: Record<string, string> = {
  '1d': '日线',
  '5m': '5 分钟',
  '15m': '15 分钟',
  '30m': '30 分钟',
  '60m': '60 分钟',
};

function pctClass(v: number | undefined): string {
  if (v === undefined || v === 0) return 'text-foreground';
  return v > 0 ? 'text-emerald-600' : 'text-red-600';
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-1 font-display text-lg tabular-nums ${tone ?? 'text-foreground'}`}>{value}</p>
    </div>
  );
}

export default function BacktestResultPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? '';
  const [result, setResult] = useState<BacktestRunResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState('');
  const [reviewText, setReviewText] = useState('');
  const [reviewing, setReviewing] = useState(false);

  useEffect(() => {
    if (!id) return;
    void (async () => {
      setLoading(true);
      setNotFound(false);
      try {
        const r = await backtestApi.get(id);
        setResult(r);
        setError(r.error || '');
      } catch (e) {
        const apiErr = e as ApiResponse;
        if (apiErr?.code === ERROR_CODES.NOT_FOUND) {
          setNotFound(true);
        } else {
          setError(apiErr?.message || '加载回测结果失败');
        }
      } finally {
        setLoading(false);
      }
    })();
  }, [id]);

  const aiReview = useCallback(async () => {
    if (!result) return;
    setReviewing(true);
    setReviewText('');
    try {
      await streamBacktestReview(result.id, {
        onDelta: (t) => setReviewText((prev) => prev + t),
        onError: (msg) => setReviewText((prev) => `${prev}\n\n⚠️ ${msg}`),
      });
    } finally {
      setReviewing(false);
    }
  }, [result]);

  const equityData = useMemo(
    () =>
      (result?.equityCurve || []).map((p) => ({
        date: p.date,
        value: p.returnPercent,
        benchmark: p.benchmark,
      })),
    [result],
  );

  if (loading) {
    return (
      <div className="container mx-auto flex min-h-[50vh] items-center justify-center p-6 text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> 加载回测结果…
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="container mx-auto max-w-lg p-6 text-center">
        <FlaskConical className="mx-auto mb-4 h-10 w-10 text-muted-foreground" />
        <h1 className="font-display text-xl tracking-tight">回测记录不存在</h1>
        <p className="mt-2 text-sm text-muted-foreground">该 ID 无对应回测结果，或您无权访问。</p>
        <Link
          href="/backtest"
          className="mt-6 inline-flex items-center gap-1.5 rounded-xl bg-brand px-4 py-2.5 text-sm font-medium text-brand-foreground"
        >
          <ArrowLeft className="h-4 w-4" /> 返回回测工作台
        </Link>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="container mx-auto max-w-lg p-6 text-center">
        <p className="text-sm text-destructive">{error || '无法加载回测结果'}</p>
        <Link href="/backtest" className="mt-4 inline-block text-sm text-brand hover:underline">
          返回回测工作台
        </Link>
      </div>
    );
  }

  const runError = result.error || error;

  const m = result.metrics || {};
  const actualRange = result.actualRange;
  const engine = ENGINES[result.config?.engine ?? result.engine] ?? result.engine;
  const frequency = FREQUENCIES[result.config?.frequency as string] ?? '日线';

  return (
    <div className="container mx-auto max-w-6xl space-y-4 p-6">
      <Link
        href="/backtest"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 回测工作台
      </Link>

      <header className="flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand">
          <FlaskConical className="h-5 w-5" />
        </span>
        <div>
          <h1 className="font-display text-xl tracking-tight">回测结果 · {result.strategyType}</h1>
          <p className="text-xs text-muted-foreground">
            {engine} · {frequency} · {result.createdAt?.slice(0, 10)}
          </p>
        </div>
      </header>

      {runError && (
        <p role="alert" className="rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-600">
          {runError}
        </p>
      )}

      {!runError && (
        <>
      <p className="rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
        回测引擎：{engine} · 回测周期：{frequency}
        {actualRange
          ? ` · 实际数据区间 ${actualRange.start.slice(0, 16)} 至 ${actualRange.end.slice(0, 16)}`
          : ''}
      </p>
      <DataQualityNotice dataQuality={result.dataQuality} />
      {result.ruleQuality?.historicalST === 'unavailable' && (
        <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
          历史 ST 状态暂无 PIT 数据；涨跌停按板块规则计算，未将当前名称倒灌到历史。
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat
          label="总收益"
          value={`${(m.totalReturnPercent ?? 0) > 0 ? '+' : ''}${m.totalReturnPercent ?? 0}%`}
          tone={pctClass(m.totalReturnPercent)}
        />
        <Stat
          label="年化"
          value={`${(m.annualReturnPercent ?? 0) > 0 ? '+' : ''}${m.annualReturnPercent ?? 0}%`}
          tone={pctClass(m.annualReturnPercent)}
        />
        <Stat label="夏普" value={`${m.sharpeRatio ?? 0}`} />
        <Stat label="最大回撤" value={`${m.maxDrawdownPercent ?? 0}%`} tone="text-red-600" />
        <Stat label="胜率" value={`${m.winRate ?? 0}%`} />
        <Stat label="盈亏比" value={`${m.profitFactor ?? 0}`} />
        <Stat label="交易数" value={`${m.totalTrades ?? 0}`} />
        <Stat
          label={`超额(vs${m.benchmarkLabel ?? '基准'})`}
          value={`${(m.excessReturnPercent ?? 0) > 0 ? '+' : ''}${m.excessReturnPercent ?? 0}%`}
          tone={pctClass(m.excessReturnPercent)}
        />
      </div>

      <div className="rounded-2xl border border-border bg-card p-4">
        <p className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
          权益曲线（累计收益率 vs {m.benchmarkLabel ?? '基准'}）
        </p>
        {equityData.length > 0 ? (
          <LineChart data={equityData} height={320} showLegend />
        ) : (
          <p className="py-10 text-center text-sm text-muted-foreground">无权益数据</p>
        )}
      </div>

      {result.trades && result.trades.length > 0 && (
        <div className="rounded-2xl border border-border bg-card p-4">
          <p className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">成交回合（前 50）</p>
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card text-muted-foreground">
                <tr className="border-b border-border text-left">
                  <th className="py-1.5">标的</th>
                  <th>买入</th>
                  <th>卖出</th>
                  <th className="text-right">收益</th>
                  <th className="text-right">收益率</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {result.trades.slice(0, 50).map((t) => (
                  <tr key={t.id} className="border-b border-border/50">
                    <td className="py-1.5">{t.symbol}</td>
                    <td>
                      {formatBacktestTime(t.entryTime, result.config?.frequency)} @ {t.entryPrice}
                    </td>
                    <td>
                      {formatBacktestTime(t.exitTime, result.config?.frequency)} @ {t.exitPrice}
                    </td>
                    <td className={`text-right ${pctClass(t.return)}`}>{t.return}</td>
                    <td className={`text-right ${pctClass(t.returnPercent)}`}>{t.returnPercent}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-border bg-card p-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs uppercase tracking-wider text-muted-foreground">AI 回测点评</p>
          <button
            onClick={aiReview}
            disabled={reviewing}
            className="rounded-lg border border-border px-3 py-1.5 text-xs transition-colors hover:border-brand/50 disabled:opacity-60"
          >
            {reviewing ? '点评中…' : 'AI 点评'}
          </button>
        </div>
        {reviewText ? (
          <Markdown content={reviewText} />
        ) : (
          <p className="text-sm text-muted-foreground">
            点击「AI 点评」让 AI 基于本次回测真实结果做策略诊断（含改进方向，非投资建议）。
          </p>
        )}
      </div>
        </>
      )}
    </div>
  );
}
