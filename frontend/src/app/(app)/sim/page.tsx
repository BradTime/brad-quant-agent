'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Wallet, Loader2, Sparkles, AlertTriangle, X, RefreshCw } from 'lucide-react';
import { RequireAuth } from '@/components/auth/require-auth';
import { Markdown } from '@/components/ai/markdown';
import {
  getSimAccount,
  getSimPositions,
  listSimOrders,
  listSimTrades,
  placeSimOrder,
  cancelSimOrder,
  streamSimReview,
  type SimAccount,
  type SimPosition,
  type SimOrder,
  type SimTrade,
} from '@/lib/api/sim';
import { getApiErrorMessage } from '@/lib/api/errors';
import { useSimTradeSocket } from '@/hooks/useSimTradeSocket';
import { cn } from '@/lib/utils';

const fmt = (v: number | null | undefined, d = 2): string =>
  v === null || v === undefined ? '—' : v.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
const signed = (v: number) => v >= 0;
const STATUS_LABEL: Record<string, string> = {
  pending: '挂单中',
  filled: '已成交',
  cancelled: '已撤销',
  rejected: '已拒绝',
  partial: '部分成交',
};

function SimView() {
  const [account, setAccount] = useState<SimAccount | null>(null);
  const [positions, setPositions] = useState<SimPosition[]>([]);
  const [orders, setOrders] = useState<SimOrder[]>([]);
  const [trades, setTrades] = useState<SimTrade[]>([]);
  const [code, setCode] = useState('600000');
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [orderType, setOrderType] = useState<'limit' | 'market'>('limit');
  const [qty, setQty] = useState(100);
  const [price, setPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ kind: 'ok' | 'err'; msg: string } | null>(null);
  const [review, setReview] = useState('');
  const [reviewing, setReviewing] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [a, p, o, t] = await Promise.all([
        getSimAccount(),
        getSimPositions(),
        listSimOrders(30),
        listSimTrades(30),
      ]);
      setAccount(a);
      setPositions(p);
      setOrders(o);
      setTrades(t);
      setLoadError(null);
    } catch (err) {
      setLoadError(getApiErrorMessage(err, '无法加载模拟账户'));
    }
  }, []);

  const onFill = useCallback(
    (payload: unknown) => {
      const order = payload as SimOrder | null;
      if (order?.status === 'filled') {
        setToast({
          kind: 'ok',
          msg: `成交回报：${order.name || order.code} ${order.side === 'buy' ? '买入' : '卖出'} ${order.qty} 股`,
        });
      } else if (order?.status === 'cancelled' || order?.status === 'rejected') {
        setToast({
          kind: 'err',
          msg: `${STATUS_LABEL[order.status] ?? order.status}：${order.reason || order.code}`,
        });
      }
      void refresh();
    },
    [refresh]
  );

  const { status: wsStatus, lastFillAt } = useSimTradeSocket(onFill);

  useEffect(() => {
    void (async () => {
      await refresh();
    })();
    return () => abortRef.current?.abort();
  }, [refresh]);

  const submit = async () => {
    if (submitting || loadError) return;
    setToast(null);
    setSubmitting(true);
    try {
      const order = await placeSimOrder({
        code: code.trim(),
        side,
        type: orderType,
        qty,
        ...(orderType === 'limit' && price ? { price: Number(price) } : {}),
      });
      if (order.status === 'rejected') {
        setToast({ kind: 'err', msg: `已拒绝：${order.reason}` });
      } else {
        setToast({ kind: 'ok', msg: `${STATUS_LABEL[order.status] ?? order.status}：${order.name || order.code} ${side === 'buy' ? '买入' : '卖出'} ${qty} 股` });
      }
      await refresh();
    } catch (err) {
      setToast({ kind: 'err', msg: getApiErrorMessage(err, '下单失败') });
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async (id: string) => {
    try {
      await cancelSimOrder(id);
      await refresh();
    } catch (err) {
      setToast({ kind: 'err', msg: getApiErrorMessage(err, '撤单失败') });
    }
  };

  const runReview = async () => {
    if (reviewing) return;
    setReview('');
    setReviewing(true);
    const controller = new AbortController();
    abortRef.current = controller;
    let acc = '';
    await streamSimReview({
      signal: controller.signal,
      onDelta: (piece) => {
        acc += piece;
        setReview(acc);
      },
      onError: (msg) => setReview((r) => r || `⚠️ ${msg}`),
    }).catch(() => {});
    setReviewing(false);
  };

  const STAT = (label: string, value: string, tone?: 'up' | 'down') => (
    <div className="rounded-xl border border-border bg-card px-4 py-3">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn('tnum mt-1 text-lg font-semibold', tone === 'up' && 'text-up', tone === 'down' && 'text-down')}>
        {value}
      </div>
    </div>
  );

  return (
    <div className="container mx-auto p-4 lg:p-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand">
            <Wallet className="h-5 w-5" />
          </span>
          <div>
            <h1 className="font-display text-2xl tracking-tight">模拟交易</h1>
            <p className="text-sm text-muted-foreground">
              play-money 模拟盘 · T+1 · 100 股整手 · 含佣金与印花税 · 仅供练习，不构成投资建议
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md border px-2 py-1',
              wsStatus === 'open'
                ? 'border-emerald-500/40 text-emerald-700 dark:text-emerald-400'
                : 'border-border'
            )}
            title={lastFillAt ? `最近回报 ${new Date(lastFillAt).toLocaleTimeString()}` : undefined}
          >
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                wsStatus === 'open' ? 'bg-emerald-500' : 'bg-muted-foreground/50'
              )}
            />
            {wsStatus === 'open' ? '实时已连接' : wsStatus === 'connecting' ? '连接中…' : '实时未连接'}
          </span>
          <button
            type="button"
            onClick={() => void refresh()}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 hover:bg-muted"
            aria-label="刷新账户"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            刷新
          </button>
        </div>
      </div>

      {loadError && (
        <div
          role="alert"
          className="mb-4 flex items-start gap-2 rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-sm"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <div className="flex-1">
            <p>{loadError}</p>
            <button type="button" className="mt-2 text-xs underline" onClick={() => void refresh()}>
              重试
            </button>
          </div>
        </div>
      )}

      {/* 账户概览 */}
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
        {STAT('总资产', fmt(account?.totalAssets))}
        {STAT('可用现金', fmt(account?.cash))}
        {STAT('持仓市值', fmt(account?.marketValue))}
        {STAT(
          '浮动盈亏',
          account ? `${signed(account.pnl) ? '+' : ''}${fmt(account.pnl)}` : '—',
          account ? (signed(account.pnl) ? 'up' : 'down') : undefined
        )}
        {STAT(
          '收益率',
          account ? `${signed(account.pnlPct) ? '+' : ''}${fmt(account.pnlPct)}%` : '—',
          account ? (signed(account.pnlPct) ? 'up' : 'down') : undefined
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-[320px_1fr]">
        {/* 下单面板 */}
        <div className="rounded-2xl border border-border bg-card p-4">
          <div className="mb-3 text-sm font-medium">下单</div>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => setSide('buy')}
              className={cn('rounded-lg border py-2 text-sm font-medium transition-colors', side === 'buy' ? 'border-up bg-up/10 text-up' : 'border-border text-muted-foreground')}
            >
              买入
            </button>
            <button
              onClick={() => setSide('sell')}
              className={cn('rounded-lg border py-2 text-sm font-medium transition-colors', side === 'sell' ? 'border-down bg-down/10 text-down' : 'border-border text-muted-foreground')}
            >
              卖出
            </button>
          </div>
          <label className="mt-3 block text-[11px] text-muted-foreground">股票代码</label>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="如 600000"
            className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-brand/50"
          />
          <div className="mt-3 inline-flex rounded-lg border border-border p-0.5 text-xs">
            {(['limit', 'market'] as const).map((t) => (
              <button
                key={t}
                onClick={() => setOrderType(t)}
                className={cn('rounded-md px-3 py-1', orderType === t ? 'bg-brand text-brand-foreground' : 'text-muted-foreground')}
              >
                {t === 'limit' ? '限价' : '市价'}
              </button>
            ))}
          </div>
          {orderType === 'limit' && (
            <>
              <label className="mt-3 block text-[11px] text-muted-foreground">价格</label>
              <input
                type="number"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="限价"
                className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-brand/50"
              />
            </>
          )}
          <label className="mt-3 block text-[11px] text-muted-foreground">数量（100 股整数倍）</label>
          <input
            type="number"
            step={100}
            min={100}
            value={qty}
            onChange={(e) => setQty(Math.max(0, Math.floor(Number(e.target.value) / 100) * 100))}
            className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm outline-none focus:border-brand/50"
          />
          <button
            onClick={submit}
            disabled={
              submitting ||
              !!loadError ||
              !code.trim() ||
              qty < 100 ||
              (orderType === 'limit' && !price)
            }
            className={cn(
              'mt-4 w-full rounded-lg py-2.5 text-sm font-medium text-white transition-opacity disabled:opacity-40',
              side === 'buy' ? 'bg-up' : 'bg-down'
            )}
          >
            {submitting ? '提交中…' : side === 'buy' ? '买入' : '卖出'}
          </button>
          {toast && (
            <div
              className={cn(
                'mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-xs',
                toast.kind === 'ok' ? 'border-border bg-muted/40 text-foreground' : 'border-destructive/40 bg-destructive/10 text-destructive'
              )}
            >
              {toast.kind === 'err' && <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
              <span>{toast.msg}</span>
            </div>
          )}
        </div>

        {/* 右侧：持仓 + 记录 + 复盘 */}
        <div className="space-y-5">
          <section className="rounded-2xl border border-border bg-card p-4">
            <div className="mb-3 flex items-center text-sm font-medium">
              持仓
              <button
                onClick={runReview}
                disabled={reviewing}
                className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
              >
                {reviewing ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3 text-brand" />}
                AI 复盘
              </button>
            </div>
            {positions.length === 0 ? (
              <p className="py-6 text-center text-xs text-muted-foreground">暂无持仓</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-muted-foreground">
                    <tr className="border-b border-border">
                      <th className="py-2 text-left font-normal">股票</th>
                      <th className="text-right font-normal">持仓/可用</th>
                      <th className="text-right font-normal">成本/现价</th>
                      <th className="text-right font-normal">市值</th>
                      <th className="text-right font-normal">盈亏</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={p.code} className="border-b border-border/50">
                        <td className="py-2">
                          <div className="font-medium">{p.name || p.code}</div>
                          <div className="text-[10px] text-muted-foreground">{p.code}</div>
                        </td>
                        <td className="tnum text-right">{p.qty}/{p.availableQty}</td>
                        <td className="tnum text-right">{fmt(p.avgCost)}/{fmt(p.price)}</td>
                        <td className="tnum text-right">{fmt(p.marketValue)}</td>
                        <td className={cn('tnum text-right', signed(p.pnl) ? 'text-up' : 'text-down')}>
                          {signed(p.pnl) ? '+' : ''}{fmt(p.pnl)}
                          <div className="text-[10px]">{signed(p.pnlPct) ? '+' : ''}{fmt(p.pnlPct)}%</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {review && (
              <div className="mt-4 rounded-xl border border-border bg-muted/20 p-3">
                <Markdown content={review} />
              </div>
            )}
          </section>

          <div className="grid gap-5 md:grid-cols-2">
            <section className="rounded-2xl border border-border bg-card p-4">
              <div className="mb-3 text-sm font-medium">委托</div>
              {orders.length === 0 ? (
                <p className="py-4 text-center text-xs text-muted-foreground">暂无委托</p>
              ) : (
                <ul className="space-y-1.5">
                  {orders.map((o) => (
                    <li key={o.id} className="flex items-center gap-2 text-xs">
                      <span className={cn('w-7 shrink-0 text-center', o.side === 'buy' ? 'text-up' : 'text-down')}>
                        {o.side === 'buy' ? '买' : '卖'}
                      </span>
                      <span className="min-w-0 flex-1 truncate">
                        {o.name || o.code}
                        <span className="text-muted-foreground"> {o.qty}股 {o.type === 'limit' ? fmt(o.price) : '市价'}</span>
                      </span>
                      <span className="shrink-0 text-muted-foreground">{STATUS_LABEL[o.status] ?? o.status}</span>
                      {o.status === 'pending' && (
                        <button onClick={() => cancel(o.id)} className="shrink-0 text-muted-foreground hover:text-destructive" aria-label="撤单">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="rounded-2xl border border-border bg-card p-4">
              <div className="mb-3 text-sm font-medium">成交</div>
              {trades.length === 0 ? (
                <p className="py-4 text-center text-xs text-muted-foreground">暂无成交</p>
              ) : (
                <ul className="space-y-1.5">
                  {trades.map((t) => (
                    <li key={t.id} className="flex items-center gap-2 text-xs">
                      <span className={cn('w-7 shrink-0 text-center', t.side === 'buy' ? 'text-up' : 'text-down')}>
                        {t.side === 'buy' ? '买' : '卖'}
                      </span>
                      <span className="min-w-0 flex-1 truncate">
                        {t.name || t.code}
                        <span className="text-muted-foreground"> {t.qty}股 @ {fmt(t.price)}</span>
                      </span>
                      <span className="tnum shrink-0 text-muted-foreground">{fmt(t.amount)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      </div>

      <p className="mt-6 text-[11px] leading-relaxed text-muted-foreground">
        模拟撮合按免费行情快照/最近收盘价；限价单不满足时挂单，由行情刷新尝试撮合。play-money，仅供练习，不构成投资建议。
      </p>
    </div>
  );
}

export default function SimPage() {
  return (
    <RequireAuth>
      <SimView />
    </RequireAuth>
  );
}
