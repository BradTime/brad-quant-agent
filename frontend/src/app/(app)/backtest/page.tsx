'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { FlaskConical, Loader2 } from 'lucide-react';
import { Markdown } from '@/components/ai/markdown';
import { LineChart } from '@/components/charts';
import {
  backtestApi,
  streamBacktestReview,
  type BacktestRunResult,
  type GridResultRow,
  type GridSearchResult,
  type StrategyCatalogItem,
} from '@/lib/api/backtest';
import { strategiesApi } from '@/lib/api/strategies';
import { formatBacktestTime } from '@/lib/utils/format';
import type { BacktestEngine, BacktestFrequency } from '@/types/backtest';
import type { Strategy } from '@/types/strategy';

const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);
const ENGINES: Array<{ value: BacktestEngine; label: string }> = [
  { value: 'native', label: 'Native（自研）' },
  { value: 'backtrader', label: 'Backtrader' },
];
const FREQUENCIES: Array<{ value: BacktestFrequency; label: string }> = [
  { value: '1d', label: '日线' },
  { value: '5m', label: '5 分钟' },
  { value: '15m', label: '15 分钟' },
  { value: '30m', label: '30 分钟' },
  { value: '60m', label: '60 分钟' },
];

function frequencyLabel(value: unknown): string {
  return FREQUENCIES.find((item) => item.value === value)?.label ?? '日线';
}

function engineLabel(value: unknown): string {
  return ENGINES.find((item) => item.value === value)?.label ?? 'Native（自研）';
}

function pctClass(v: number | undefined): string {
  if (v === undefined || v === 0) return 'text-foreground';
  return v > 0 ? 'text-emerald-600' : 'text-red-600';
}

function defaultParams(item: StrategyCatalogItem): Record<string, number> {
  return Object.fromEntries(item.params.map((p) => [p.key, p.default]));
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-1 font-display text-lg tabular-nums ${tone ?? 'text-foreground'}`}>{value}</p>
    </div>
  );
}

export default function BacktestPage() {
  const [catalog, setCatalog] = useState<StrategyCatalogItem[]>([]);
  const [savedStrategies, setSavedStrategies] = useState<Strategy[]>([]);
  const [savedStrategyId, setSavedStrategyId] = useState('');
  const [strategyType, setStrategyType] = useState('dual_ma');
  const [params, setParams] = useState<Record<string, number>>({});
  const [codes, setCodes] = useState('600000.SH');
  const [start, setStart] = useState(daysAgo(730));
  const [end, setEnd] = useState(today());
  const [capital, setCapital] = useState(1_000_000);
  const [slippage, setSlippage] = useState(0.001);
  const [engine, setEngine] = useState<BacktestEngine>('native');
  const [frequency, setFrequency] = useState<BacktestFrequency>('1d');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<BacktestRunResult | null>(null);
  const [history, setHistory] = useState<BacktestRunResult[]>([]);
  const [reviewText, setReviewText] = useState('');
  const [reviewing, setReviewing] = useState(false);
  const [gridMode, setGridMode] = useState(false);
  const [gridCand, setGridCand] = useState<Record<string, string>>({});
  const [sortBy, setSortBy] = useState('sharpeRatio');
  const [gridResult, setGridResult] = useState<GridSearchResult | null>(null);
  const [gridRunning, setGridRunning] = useState(false);

  const current = useMemo(
    () => catalog.find((c) => c.type === strategyType),
    [catalog, strategyType],
  );

  const refreshHistory = useCallback(async () => {
    try {
      const r = await backtestApi.list();
      setHistory(r.items || []);
    } catch {
      /* 历史加载失败不阻塞主流程 */
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const c = await backtestApi.strategyCatalog();
        const items = c.items || [];
        setCatalog(items);
        const found = items.find((x) => x.type === strategyType);
        if (found) setParams(defaultParams(found));
      } catch {
        /* 目录加载失败：仍可用默认 dual_ma */
      }
      try {
        const saved = await strategiesApi.getList({
          page: 1,
          pageSize: 100,
          sortBy: 'updatedAt',
          sortOrder: 'desc',
        });
        setSavedStrategies(saved.items || []);
      } catch {
        /* 已保存策略加载失败不阻塞直接配置内置策略 */
      }
      await refreshHistory();
    })();
    // 首挂载加载策略目录与历史（一次性初始化）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = useCallback(async () => {
    setRunning(true);
    setError('');
    setReviewText('');
    try {
      const res = await backtestApi.run({
        strategyType,
        params,
        codes: codes.split(',').map((s) => s.trim()).filter(Boolean),
        start,
        end,
        initialCapital: capital,
        slippage,
        engine,
        frequency,
      });
      setResult(res);
      setError(res.error || '');
      await refreshHistory();
    } catch (e) {
      setError((e as { message?: string })?.message || '回测失败，请稍后重试');
    } finally {
      setRunning(false);
    }
  }, [
    strategyType,
    params,
    codes,
    start,
    end,
    capital,
    slippage,
    engine,
    frequency,
    refreshHistory,
  ]);

  const loadReport = useCallback(async (id: string) => {
    try {
      const r = await backtestApi.get(id);
      setResult(r);
      setError(r.error || '');
      setReviewText('');
    } catch {
      /* ignore */
    }
  }, []);

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

  const runGrid = useCallback(async () => {
    setGridRunning(true);
    setError('');
    setGridResult(null);
    try {
      const paramGrid: Record<string, number[]> = {};
      (current?.params || []).forEach((p) => {
        const raw = gridCand[p.key] ?? String(params[p.key] ?? p.default);
        const vals = raw
          .split(',')
          .map((s) => Number(s.trim()))
          .filter((n) => !Number.isNaN(n));
        if (vals.length) paramGrid[p.key] = vals;
      });
      const res = await backtestApi.gridSearch({
        strategyType,
        paramGrid,
        codes: codes.split(',').map((s) => s.trim()).filter(Boolean),
        start,
        end,
        initialCapital: capital,
        slippage,
        engine,
        sortBy,
        frequency,
      });
      setGridResult(res);
      setError(res.error || '');
    } catch (e) {
      setError((e as { message?: string })?.message || '寻优失败，请稍后重试');
    } finally {
      setGridRunning(false);
    }
  }, [
    current,
    gridCand,
    params,
    strategyType,
    codes,
    start,
    end,
    capital,
    slippage,
    engine,
    sortBy,
    frequency,
  ]);

  const applyRow = useCallback((row: GridResultRow) => {
    setParams((prev) => ({ ...prev, ...row.params }));
    setGridMode(false);
    setGridResult(null);
  }, []);

  const equityData = useMemo(
    () =>
      (result?.equityCurve || []).map((p) => ({
        date: p.date,
        value: p.returnPercent,
        benchmark: p.benchmark,
      })),
    [result],
  );
  const m = result?.metrics || {};
  const partialData = Object.values(result?.dataQuality || {}).includes('none');
  const actualRange = result?.actualRange;

  return (
    <div className="container mx-auto max-w-6xl p-6">
      <header className="mb-6 flex items-center gap-3">
        <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand">
          <FlaskConical className="h-5 w-5" />
        </span>
        <div>
          <h1 className="font-display text-xl tracking-tight">策略回测</h1>
          <p className="text-xs text-muted-foreground">
            后复权 · T+1 · 涨跌停 · 佣金/印花税/滑点 · 下一根开盘成交（防前视）
          </p>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        {/* 配置 + 历史 */}
        <div className="space-y-4">
          <div className="space-y-3 rounded-2xl border border-border bg-card p-4">
            <label className="block text-sm">
              <span className="text-muted-foreground">已保存策略</span>
              <select
                value={savedStrategyId}
                onChange={(e) => {
                  const id = e.target.value;
                  setSavedStrategyId(id);
                  const saved = savedStrategies.find((item) => item.id === id);
                  if (saved) {
                    setStrategyType(saved.builtinType);
                    setParams({ ...saved.params });
                    setGridMode(false);
                    setGridResult(null);
                  }
                }}
                className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                <option value="">不使用已保存策略</option>
                {savedStrategies.map((saved) => (
                  <option key={saved.id} value={saved.id}>
                    {saved.name} · {saved.builtinType}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-muted-foreground">
                选择后自动预填内置策略类型与参数
              </span>
            </label>

            <label className="block text-sm">
              <span className="text-muted-foreground">内置策略类型</span>
              <select
                value={strategyType}
                onChange={(e) => {
                  const t = e.target.value;
                  setSavedStrategyId('');
                  setStrategyType(t);
                  const found = catalog.find((x) => x.type === t);
                  if (found) setParams(defaultParams(found));
                }}
                className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                {(catalog.length ? catalog : [{ type: 'dual_ma', name: '双均线' }]).map((c) => (
                  <option key={c.type} value={c.type}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            {current?.description && (
              <p className="text-xs text-muted-foreground">{current.description}</p>
            )}

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={gridMode}
                onChange={(e) => setGridMode(e.target.checked)}
              />
              <span className="text-muted-foreground">参数寻优（网格搜索）</span>
            </label>

            {current?.params.map((p) =>
              gridMode ? (
                <label key={p.key} className="block text-sm">
                  <span className="text-muted-foreground">{p.label}（候选值，逗号分隔）</span>
                  <input
                    value={gridCand[p.key] ?? String(params[p.key] ?? p.default)}
                    onChange={(e) => setGridCand((prev) => ({ ...prev, [p.key]: e.target.value }))}
                    placeholder={`如 ${p.default},${p.default * 2}`}
                    className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm tabular-nums"
                  />
                </label>
              ) : (
                <label key={p.key} className="block text-sm">
                  <span className="text-muted-foreground">{p.label}</span>
                  <input
                    type="number"
                    value={params[p.key] ?? p.default}
                    min={p.min}
                    max={p.max}
                    step={p.type === 'float' ? 0.01 : 1}
                    onChange={(e) =>
                      setParams((prev) => ({ ...prev, [p.key]: Number(e.target.value) }))
                    }
                    className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm tabular-nums"
                  />
                </label>
              ),
            )}

            <label className="block text-sm">
              <span className="text-muted-foreground">标的（逗号分隔）</span>
              <input
                value={codes}
                onChange={(e) => setCodes(e.target.value)}
                placeholder="600000.SH, 000001.SZ"
                className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              />
            </label>

            <label className="block text-sm">
              <span className="text-muted-foreground">回测引擎</span>
              <select
                value={engine}
                onChange={(e) => {
                  setEngine(e.target.value as BacktestEngine);
                  setGridResult(null);
                  setResult(null);
                  setReviewText('');
                  setError('');
                }}
                className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                {ENGINES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
              {engine === 'backtrader' && (
                <span className="mt-1 block text-xs text-muted-foreground">
                  Cerebro 数据调度；A 股 T+1、费税与涨跌停沿用统一撮合口径
                </span>
              )}
            </label>

            <label className="block text-sm">
              <span className="text-muted-foreground">回测周期</span>
              <select
                value={frequency}
                onChange={(e) => setFrequency(e.target.value as BacktestFrequency)}
                className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
              >
                {FREQUENCIES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
              {frequency !== '1d' && (
                <span className="mt-1 block text-xs text-muted-foreground">
                  分钟数据仅使用已回填记录，缺失时不会触发实时抓取
                </span>
              )}
            </label>

            <div className="grid grid-cols-2 gap-2">
              <label className="block text-sm">
                <span className="text-muted-foreground">开始</span>
                <input
                  type="date"
                  value={start}
                  onChange={(e) => setStart(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-border bg-background px-2 py-2 text-sm"
                />
              </label>
              <label className="block text-sm">
                <span className="text-muted-foreground">结束</span>
                <input
                  type="date"
                  value={end}
                  onChange={(e) => setEnd(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-border bg-background px-2 py-2 text-sm"
                />
              </label>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <label className="block text-sm">
                <span className="text-muted-foreground">初始资金</span>
                <input
                  type="number"
                  value={capital}
                  onChange={(e) => setCapital(Number(e.target.value))}
                  className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm tabular-nums"
                />
              </label>
              <label className="block text-sm">
                <span className="text-muted-foreground">滑点</span>
                <input
                  type="number"
                  step={0.001}
                  value={slippage}
                  onChange={(e) => setSlippage(Number(e.target.value))}
                  className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm tabular-nums"
                />
              </label>
            </div>

            {gridMode && (
              <label className="block text-sm">
                <span className="text-muted-foreground">排序指标</span>
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
                >
                  <option value="sharpeRatio">夏普比率</option>
                  <option value="totalReturnPercent">总收益</option>
                  <option value="annualReturnPercent">年化收益</option>
                  <option value="maxDrawdownPercent">最大回撤（小优先）</option>
                  <option value="excessReturnPercent">超额收益</option>
                </select>
              </label>
            )}
            <button
              onClick={gridMode ? runGrid : run}
              disabled={gridMode ? gridRunning : running}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-sm font-medium text-brand-foreground disabled:opacity-60"
            >
              {(gridMode ? gridRunning : running) ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FlaskConical className="h-4 w-4" />
              )}
              {gridMode
                ? gridRunning
                  ? '寻优中…'
                  : '网格寻优'
                : running
                  ? '回测中…'
                  : '运行回测'}
            </button>
            {error && <p className="text-xs text-red-600">{error}</p>}
          </div>

          {history.length > 0 && (
            <div className="rounded-2xl border border-border bg-card p-4">
              <p className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">历史回测</p>
              <ul className="space-y-1.5">
                {history.map((h) => (
                  <li key={h.id}>
                    <button
                      onClick={() => loadReport(h.id)}
                      className="w-full rounded-lg px-2 py-1.5 text-left text-xs transition-colors hover:bg-brand-soft"
                    >
                      <span className="text-foreground">{h.strategyType}</span>
                      <span className={`ml-2 tabular-nums ${pctClass(h.metrics?.totalReturnPercent)}`}>
                        {h.metrics?.totalReturnPercent != null
                          ? `${h.metrics.totalReturnPercent > 0 ? '+' : ''}${h.metrics.totalReturnPercent}%`
                          : h.status}
                      </span>
                      <span className="ml-2 text-muted-foreground">
                        {engineLabel(h.config?.engine ?? h.engine)} ·{' '}
                        {frequencyLabel(h.config?.frequency)} · {h.createdAt?.slice(0, 10)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* 结果 */}
        <div className="space-y-4">
          {!gridMode && !result && (
            <div className="grid min-h-[300px] place-items-center rounded-2xl border border-dashed border-border text-sm text-muted-foreground">
              配置左侧参数后点「运行回测」查看权益曲线与绩效
            </div>
          )}

          {gridMode && (
            <div className="rounded-2xl border border-border bg-card p-4">
              <p className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
                参数寻优结果 · {engineLabel(gridResult?.engine ?? engine)}
                {gridResult?.truncated ? '（超上限，已截断至 64 组）' : ''}
              </p>
              {gridResult?.actualRange && (
                <p className="mb-3 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
                  实际共同数据区间：{gridResult.actualRange.start.slice(0, 16)} 至{' '}
                  {gridResult.actualRange.end.slice(0, 16)}
                </p>
              )}
              {gridResult?.ruleQuality?.historicalST === 'unavailable' && (
                <p className="mb-3 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
                  历史 ST 状态暂无 PIT 数据；涨跌停按板块规则计算，未将当前名称倒灌到历史。
                </p>
              )}
              {gridResult && gridResult.results.length > 0 ? (
                <div className="max-h-[520px] overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-card text-muted-foreground">
                      <tr className="border-b border-border text-left">
                        <th className="py-1.5">参数</th>
                        <th className="text-right">总收益</th>
                        <th className="text-right">夏普</th>
                        <th className="text-right">回撤</th>
                        <th className="text-right">胜率</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody className="tabular-nums">
                      {gridResult.results.map((r, i) => (
                        <tr
                          key={i}
                          className={`border-b border-border/50 ${i === 0 ? 'bg-brand-soft/50' : ''}`}
                        >
                          <td className="py-1.5">
                            {Object.entries(r.params)
                              .map(([k, v]) => `${k}=${v}`)
                              .join('  ')}
                          </td>
                          <td className={`text-right ${pctClass(r.metrics.totalReturnPercent)}`}>
                            {r.metrics.totalReturnPercent}%
                          </td>
                          <td className="text-right">{r.metrics.sharpeRatio}</td>
                          <td className="text-right text-red-600">
                            {r.metrics.maxDrawdownPercent}%
                          </td>
                          <td className="text-right">{r.metrics.winRate}%</td>
                          <td className="text-right">
                            <button
                              onClick={() => applyRow(r)}
                              className="rounded border border-border px-2 py-0.5 text-[11px] hover:border-brand/50"
                            >
                              用此参数
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  为参数填候选值（逗号分隔）后点「网格寻优」，查看参数 × 绩效排名。
                </p>
              )}
            </div>
          )}

          {!gridMode && result && !result.error && (
            <>
              <p className="rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
                回测引擎：{engineLabel(result.config?.engine ?? result.engine)} · 回测周期：
                {frequencyLabel(result.config?.frequency)}
                {actualRange
                  ? ` · 实际数据区间 ${actualRange.start.slice(0, 16)} 至 ${actualRange.end.slice(0, 16)}`
                  : ''}
              </p>
              {partialData && (
                <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
                  部分标的缺少复权因子（数据质量降级），建议先 backfill 补全后再回测。
                </p>
              )}
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
                <Stat
                  label="最大回撤"
                  value={`${m.maxDrawdownPercent ?? 0}%`}
                  tone="text-red-600"
                />
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
                  <p className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
                    成交回合（前 50）
                  </p>
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
                              {formatBacktestTime(t.entryTime, result.config?.frequency)} @{' '}
                              {t.entryPrice}
                            </td>
                            <td>
                              {formatBacktestTime(t.exitTime, result.config?.frequency)} @{' '}
                              {t.exitPrice}
                            </td>
                            <td className={`text-right ${pctClass(t.return)}`}>{t.return}</td>
                            <td className={`text-right ${pctClass(t.returnPercent)}`}>
                              {t.returnPercent}%
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              <div className="rounded-2xl border border-border bg-card p-4">
                <div className="mb-2 flex items-center justify-between">
                  <p className="text-xs uppercase tracking-wider text-muted-foreground">
                    AI 回测点评
                  </p>
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
      </div>
    </div>
  );
}
