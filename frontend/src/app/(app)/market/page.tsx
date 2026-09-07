'use client';

import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RefreshCw, AlertTriangle } from 'lucide-react';
import { RequireAuth } from '@/components/auth/require-auth';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { SearchBox } from '@/components/market/search-box';
import { WatchlistPanel } from '@/components/market/watchlist-panel';
import { QuotesTable } from '@/components/market/quotes-table';
import { ScreenerPanel } from '@/components/market/screener-panel';
import { SourceNote } from '@/components/market/source-note';
import { dashboardApi } from '@/lib/api/dashboard';
import { marketApi } from '@/lib/api/market';
import { ageQuote, formatQuoteFreshness } from '@/lib/api/quote-selection';
import { useFreshnessClock } from '@/hooks/useFreshnessClock';
import { useMarketSocket } from '@/hooks/useMarketSocket';
import type { MarketOverview } from '@/types/dashboard';
import { cn } from '@/lib/utils';

type Tab = 'all' | 'screener';

function changeClass(value: number | null): string {
  if (value === null || value === 0) return 'text-muted-foreground';
  return value > 0 ? 'text-up' : 'text-down';
}

function fixed(value: number | null): string {
  return value === null ? '—' : value.toFixed(2);
}

function signed(value: number | null, suffix = ''): string {
  return value === null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}${suffix}`;
}

export default function MarketPage() {
  const [tab, setTab] = useState<Tab>('all');
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const [sortBy, setSortBy] = useState<'price' | 'changePercent' | 'volume'>('changePercent');
  const freshnessNow = useFreshnessClock();
  const { status: wsStatus, data: wsData, receivedAt: wsReceivedAt } =
    useMarketSocket(['market.indices']);

  const {
    data: indices = [],
    dataUpdatedAt: indicesReceivedAt,
    isError: indicesError,
    isFetching: indicesFetching,
    refetch: refetchIndices,
  } = useQuery({
    queryKey: ['dashboard', 'market-overview'],
    queryFn: () => dashboardApi.getMarketOverview(),
    refetchInterval: wsStatus === 'open' ? false : 10000,
  });

  const wsIndices = wsData['market.indices'] as MarketOverview[] | undefined;
  const displayIndices = useMemo(() => {
    if (wsStatus !== 'open' || !Array.isArray(wsIndices) || wsIndices.length === 0) {
      return indices;
    }
    return wsIndices;
  }, [indices, wsIndices, wsStatus]);
  const indicesClock = wsStatus === 'open' && wsIndices?.length
    ? (wsReceivedAt['market.indices'] ?? indicesReceivedAt)
    : indicesReceivedAt;

  const {
    data: quotesData,
    dataUpdatedAt: quotesReceivedAt,
    isError: quotesError,
    isFetching: quotesFetching,
    refetch: refetchQuotes,
  } = useQuery({
    queryKey: ['market', 'quotes', page, pageSize, sortBy],
    queryFn: () => marketApi.getQuotes(page, pageSize, sortBy, 'desc'),
    refetchInterval: 6000,
    enabled: tab === 'all',
  });

  const agedIndices = displayIndices.map((index) =>
    ageQuote(index, indicesClock, freshnessNow)
  );
  const stocks = (quotesData?.stocks ?? []).map((quote) =>
    ageQuote(quote, quotesReceivedAt, freshnessNow)
  );
  const quoteSummary = stocks[0];
  const total = quotesData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const quotesEmpty = tab === 'all' && stocks.length === 0;
  const quotesStaleAt = quotesReceivedAt
    ? new Date(quotesReceivedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null;
  const indicesStaleAt = indicesReceivedAt
    ? new Date(indicesReceivedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    : null;

  return (
    <RequireAuth>
      <div className="container mx-auto space-y-5 p-4 lg:p-6">
        <div>
          <h1 className="font-display text-3xl tracking-tight">看盘工作台</h1>
          <p className="mt-1 text-sm text-muted-foreground">指数 · 自选 · 全市场行情 · 条件选股 — 点任意个股进入详情</p>
        </div>

        {/* 指数概览 */}
        <div className="grid gap-3 sm:grid-cols-3">
          {agedIndices.map((idx) => {
            const freshness = formatQuoteFreshness(idx);
            return (
              <Card key={idx.index}>
                <CardContent className="p-4">
                  <div className="text-xs text-muted-foreground">{idx.name}</div>
                  <div className={cn('tnum mt-1 text-2xl font-semibold', changeClass(idx.change))}>
                    {fixed(idx.value)}
                  </div>
                  <div className={cn('tnum text-sm font-medium', changeClass(idx.change))}>
                    {signed(idx.change)} ({signed(idx.changePercent, '%')})
                  </div>
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    {freshness.text}
                  </div>
                </CardContent>
              </Card>
            );
          })}
          {agedIndices.length === 0 && (
            <Card className="sm:col-span-3">
              <CardContent className="space-y-3 p-4 text-sm text-muted-foreground">
                <div className="flex items-start gap-2">
                  {(indicesError || indicesFetching) && (
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                  )}
                  <div>
                    <p>指数行情暂不可用（免费源可能限流，稍后自动恢复）</p>
                    {indicesStaleAt && (
                      <p className="mt-1 text-xs">上次更新 {indicesStaleAt}{indicesFetching ? ' · 刷新中…' : ''}</p>
                    )}
                  </div>
                </div>
                {(indicesError || agedIndices.length === 0) && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => refetchIndices()}
                    disabled={indicesFetching}
                  >
                    <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', indicesFetching && 'animate-spin')} />
                    立即重试
                  </Button>
                )}
              </CardContent>
            </Card>
          )}
        </div>

        <SearchBox />

        <div className="grid gap-5 lg:grid-cols-3">
          {/* 自选股 */}
          <div className="lg:col-span-1">
            <Card className="lg:sticky lg:top-6">
              <CardHeader className="pb-2">
                <CardTitle className="text-base">自选股</CardTitle>
              </CardHeader>
              <CardContent>
                <WatchlistPanel />
              </CardContent>
            </Card>
          </div>

          {/* 全市场 / 选股 */}
          <div className="lg:col-span-2">
            <Card>
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <div className="flex gap-1">
                    <button
                      onClick={() => setTab('all')}
                      className={cn(
                        'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                        tab === 'all' ? 'bg-brand text-brand-foreground' : 'text-muted-foreground hover:bg-muted'
                      )}
                    >
                      全市场行情
                    </button>
                    <button
                      onClick={() => setTab('screener')}
                      className={cn(
                        'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                        tab === 'screener' ? 'bg-brand text-brand-foreground' : 'text-muted-foreground hover:bg-muted'
                      )}
                    >
                      条件选股
                    </button>
                  </div>
                  {tab === 'all' && (
                    <div className="flex items-center gap-2">
                      {quoteSummary ? (
                        <SourceNote
                          source="东方财富·快照"
                          asOf={quoteSummary.asOf}
                          staleReason={quoteSummary.staleReason}
                          executable={quoteSummary.executable}
                        />
                      ) : (
                        <SourceNote source="东方财富·快照" freshness="不可用" limited />
                      )}
                      <select
                        value={sortBy}
                        onChange={(e) => {
                          setSortBy(e.target.value as typeof sortBy);
                          setPage(1);
                        }}
                        className="rounded-md border border-border bg-background px-2 py-1 text-xs outline-none"
                      >
                        <option value="changePercent">按涨跌幅</option>
                        <option value="price">按现价</option>
                        <option value="volume">按成交量</option>
                      </select>
                    </div>
                  )}
                </div>
              </CardHeader>
              <CardContent>
                {tab === 'all' ? (
                  <>
                    {(quotesError || quotesEmpty) && (
                      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
                        <div className="flex items-start gap-2">
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                          <div>
                            <p>{quotesError ? '行情加载失败' : '暂无行情数据'}</p>
                            {quotesStaleAt && (
                              <p className="mt-0.5 text-[11px] opacity-80">
                                上次更新 {quotesStaleAt}{quotesFetching ? ' · 刷新中…' : ''}
                              </p>
                            )}
                          </div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => refetchQuotes()}
                          disabled={quotesFetching}
                        >
                          <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', quotesFetching && 'animate-spin')} />
                          立即重试
                        </Button>
                      </div>
                    )}
                    <QuotesTable
                      stocks={stocks}
                      emptyText="行情暂不可用（免费行情源可能限流，稍后自动恢复）"
                    />
                    {total > pageSize && (
                      <div className="mt-3 flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">共 {total} 只</span>
                        <div className="flex items-center gap-2">
                          <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
                            上一页
                          </Button>
                          <span className="text-xs">{page} / {totalPages}</span>
                          <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
                            下一页
                          </Button>
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <ScreenerPanel />
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </RequireAuth>
  );
}
