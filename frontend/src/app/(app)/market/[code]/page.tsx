'use client';

import { useMemo, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  RefreshCw,
  Star,
  StarOff,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { RequireAuth } from '@/components/auth/require-auth';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  CandlestickChart,
  type MainOverlay,
  type SubIndicator,
} from '@/components/charts';
import { ChatPanel } from '@/components/ai/chat-panel';
import { SourceNote } from '@/components/market/source-note';
import { marketApi, type KlinePeriod, type StockQuote } from '@/lib/api/market';
import { selectDisplayQuote } from '@/lib/api/quote-selection';
import { watchlistApi } from '@/lib/api/watchlist';
import { watchlistQueryKeys } from '@/components/market/watchlist-query-keys';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { useFreshnessClock } from '@/hooks/useFreshnessClock';
import { useMarketSocket } from '@/hooks/useMarketSocket';
import { useAuthStore } from '@/stores/useAuthStore';
import { formatAmount } from '@/lib/utils/format';
import { cn } from '@/lib/utils';
import type { ApiResponse } from '@/types';
import { ERROR_CODES } from '@/lib/constants';

const PERIODS: { key: KlinePeriod; label: string }[] = [
  { key: 'day', label: '日K' },
  { key: 'hour', label: '60分' },
  { key: '30min', label: '30分' },
  { key: '15min', label: '15分' },
  { key: '5min', label: '5分' },
];

const OVERLAYS: { key: MainOverlay; label: string }[] = [
  { key: 'ma', label: 'MA' },
  { key: 'boll', label: 'BOLL' },
  { key: 'none', label: '无' },
];

const SUBS: { key: SubIndicator; label: string }[] = [
  { key: 'macd', label: 'MACD' },
  { key: 'kdj', label: 'KDJ' },
  { key: 'rsi', label: 'RSI' },
  { key: 'none', label: '无' },
];

type PanelKey = 'overview' | 'capital' | 'financial' | 'lhb' | 'news';
const PANELS: { key: PanelKey; label: string }[] = [
  { key: 'overview', label: '概览' },
  { key: 'capital', label: '资金流' },
  { key: 'financial', label: '财务摘要' },
  { key: 'lhb', label: '龙虎榜' },
  { key: 'news', label: '新闻公告' },
];

function changeClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return 'text-muted-foreground';
  return v > 0 ? 'text-up' : 'text-down';
}

function sign(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`;
}

export default function StockDetailPage() {
  const params = useParams<{ code: string }>();
  const rawCode = decodeURIComponent(params?.code ?? '');
  const queryClient = useQueryClient();
  const userId = useAuthStore((s) => s.user?.id);

  const [period, setPeriod] = useState<KlinePeriod>('day');
  const [overlay, setOverlay] = useState<MainOverlay>('ma');
  const [sub, setSub] = useState<SubIndicator>('macd');
  const [panel, setPanel] = useState<PanelKey>('overview');
  const [watchGroup, setWatchGroup] = useState('默认分组');
  const [newWatchGroup, setNewWatchGroup] = useState('');
  const freshnessNow = useFreshnessClock();
  const quoteTopic = `market.quote.${rawCode}`;

  const {
    status: wsStatus,
    data: wsData,
    receivedAt: wsReceivedAt,
  } = useMarketSocket(rawCode ? [quoteTopic] : []);

  const { data: quote, dataUpdatedAt: quoteReceivedAt, isError: quoteError, error: quoteErr } = useQuery({
    queryKey: ['market', 'quote', rawCode],
    queryFn: () => marketApi.getQuote(rawCode),
    refetchInterval: (query) => {
      const err = query.state.error as unknown as ApiResponse | undefined;
      if (err?.code === ERROR_CODES.NOT_FOUND) return false;
      if (wsStatus === 'open') return false;
      return 6000;
    },
    retry: false,
  });

  const isQuoteNotFound =
    quoteError && (quoteErr as unknown as ApiResponse | undefined)?.code === ERROR_CODES.NOT_FOUND;

  const canonical = quote?.code ?? rawCode;
  const liveQuote = (wsData[quoteTopic] as StockQuote | undefined) ?? undefined;
  const q = selectDisplayQuote(
    quote,
    liveQuote,
    wsStatus,
    quoteReceivedAt,
    wsReceivedAt[quoteTopic] ?? 0,
    freshnessNow
  );

  const { data: profile } = useQuery({
    queryKey: ['market', 'profile', canonical],
    queryFn: () => marketApi.getStockProfile(canonical),
    enabled: !!canonical,
    retry: false,
  });

  const { data: klineResult, isLoading: klineLoading } = useQuery({
    queryKey: ['market', 'kline', canonical, period],
    queryFn: () => marketApi.getKline(canonical, period, 250),
    enabled: !!canonical,
    retry: false,
  });
  const kline = klineResult?.bars ?? [];
  const klineQuality = klineResult?.dataQuality;

  const { data: capitalFlow = [] } = useQuery({
    queryKey: ['market', 'capital', canonical],
    queryFn: () => marketApi.getCapitalFlow(canonical, 20),
    enabled: !!canonical && panel === 'capital',
    retry: false,
  });

  const { data: financials = [] } = useQuery({
    queryKey: ['market', 'financials', canonical],
    queryFn: () => marketApi.getFinancials(canonical, 8),
    enabled: !!canonical && panel === 'financial',
    retry: false,
  });

  const { data: dragonTiger = [] } = useQuery({
    queryKey: ['market', 'lhb', canonical],
    queryFn: () => marketApi.getDragonTiger(canonical, 20),
    enabled: !!canonical && panel === 'lhb',
    retry: false,
  });

  const { data: news = [] } = useQuery({
    queryKey: ['market', 'news', canonical],
    queryFn: () => marketApi.getNews(canonical, 20),
    enabled: !!canonical && panel === 'news',
    retry: false,
  });

  const { data: watchlist = [] } = useQuery({
    queryKey: watchlistQueryKeys.all(userId),
    queryFn: () => watchlistApi.getList(),
    enabled: Boolean(userId),
    retry: false,
  });
  const { data: watchGroups = ['默认分组'] } = useQuery({
    queryKey: watchlistQueryKeys.groups(userId),
    queryFn: () => watchlistApi.getGroups(),
    enabled: Boolean(userId),
    retry: false,
  });
  const isWatched = watchlist.some((w) => w.code === canonical);

  const toggleWatch = useMutation({
    mutationFn: async () => {
      if (isWatched) await watchlistApi.remove(canonical);
      else {
        const group = newWatchGroup.trim() || watchGroup || '默认分组';
        await watchlistApi.add(canonical, { name: q?.name, group });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: watchlistQueryKeys.all(userId) });
      queryClient.invalidateQueries({ queryKey: watchlistQueryKeys.groups(userId) });
    },
  });

  const refresh = useMutation({
    mutationFn: () => marketApi.refresh(canonical),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['market', 'kline', canonical] });
      queryClient.invalidateQueries({ queryKey: ['market', 'capital', canonical] });
      queryClient.invalidateQueries({ queryKey: ['market', 'financials', canonical] });
      queryClient.invalidateQueries({ queryKey: ['market', 'news', canonical] });
    },
  });

  const contextHint = useMemo(
    () =>
      `用户正在查看个股：${canonical}${q?.name ? ` ${q.name}` : ''}${
        profile?.industry ? `（所属行业：${profile.industry}）` : ''
      }。当用户说"这只/该股/它/本股"时，默认指代该股票（代码 ${canonical}）。`,
    [canonical, q?.name, profile?.industry]
  );

  return (
    <RequireAuth>
      {isQuoteNotFound ? (
        <div className="container mx-auto max-w-lg p-10 text-center">
          <h1 className="font-display text-2xl tracking-tight">未找到该标的</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            代码「{rawCode}」不存在或暂无行情数据，请检查代码格式（如 600000.SH）。
          </p>
          <Link
            href="/market"
            className="mt-6 inline-flex items-center gap-1.5 rounded-xl bg-brand px-4 py-2.5 text-sm font-medium text-brand-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> 返回看盘工作台
          </Link>
        </div>
      ) : (
      <div className="container mx-auto space-y-5 p-4 lg:p-6">
        {/* 顶部导航 */}
        <div className="flex items-center justify-between">
          <Link
            href="/market"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" /> 看盘工作台
          </Link>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => refresh.mutate()}
              disabled={refresh.isPending || isQuoteNotFound}
            >
              <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', refresh.isPending && 'animate-spin')} />
              {refresh.isPending ? '落库中…' : '刷新数据'}
            </Button>
            {!isWatched && (
              <>
                <Select value={watchGroup} onValueChange={setWatchGroup}>
                  <SelectTrigger className="h-8 w-[120px] text-xs">
                    <SelectValue placeholder="分组" />
                  </SelectTrigger>
                  <SelectContent>
                    {[...new Set([...watchGroups, '默认分组'])].sort().map((g) => (
                      <SelectItem key={g} value={g} className="text-xs">
                        {g}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  value={newWatchGroup}
                  onChange={(e) => setNewWatchGroup(e.target.value)}
                  placeholder="或新建分组"
                  className="h-8 w-[120px] text-xs"
                />
              </>
            )}
            <Button
              variant={isWatched ? 'default' : 'outline'}
              size="sm"
              onClick={() => toggleWatch.mutate()}
              disabled={toggleWatch.isPending || isQuoteNotFound}
            >
              {isWatched ? (
                <><StarOff className="mr-1.5 h-3.5 w-3.5" /> 移出自选</>
              ) : (
                <><Star className="mr-1.5 h-3.5 w-3.5" /> 加自选</>
              )}
            </Button>
          </div>
        </div>

        {/* 行情头部 */}
        <Card>
          <CardContent className="flex flex-wrap items-end justify-between gap-4 p-5">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="font-display text-2xl tracking-tight">{q?.name || canonical}</h1>
                <span className="font-mono text-sm text-muted-foreground">{canonical}</span>
                {profile?.industry && (
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {profile.industry}
                  </span>
                )}
              </div>
              <div className="mt-3 flex items-baseline gap-3">
                <span
                  data-testid="stock-quote-price"
                  className={cn('tnum text-4xl font-semibold', changeClass(q?.change))}
                >
                  {q?.price != null ? q.price.toFixed(2) : '—'}
                </span>
                <span className={cn('tnum text-lg font-medium', changeClass(q?.change))}>
                  {sign(q?.change)} ({sign(q?.changePercent)}%)
                </span>
              </div>
            </div>
            <div className="flex flex-col items-end gap-1.5 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                {wsStatus === 'open' ? (
                  <><Wifi className="h-3.5 w-3.5 text-up" /> 实时推送</>
                ) : (
                  <><WifiOff className="h-3.5 w-3.5" /> 未连接</>
                )}
              </span>
              <SourceNote
                source={q?.staleReason === 'last_close' ? '落库收盘价' : '东方财富·快照'}
                asOf={q?.asOf}
                staleReason={q?.staleReason}
                executable={q?.executable}
                limited={q != null && q.asOf == null}
              />
              <div className="tnum mt-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-right">
                <span>今开 {q?.open != null ? q.open.toFixed(2) : '—'}</span>
                <span>最高 {q?.high != null ? q.high.toFixed(2) : '—'}</span>
                <span>昨收 {q?.yesterdayClose != null ? q.yesterdayClose.toFixed(2) : '—'}</span>
                <span>最低 {q?.low != null ? q.low.toFixed(2) : '—'}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-5 lg:grid-cols-3">
          {/* 左：K线 + 面板 */}
          <div className="space-y-5 lg:col-span-2">
            <Card>
              <CardHeader className="gap-3 pb-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap gap-1">
                    {PERIODS.map((p) => (
                      <button
                        key={p.key}
                        type="button"
                        aria-pressed={period === p.key}
                        onClick={() => setPeriod(p.key)}
                        className={cn(
                          'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                          period === p.key
                            ? 'bg-brand text-brand-foreground'
                            : 'text-muted-foreground hover:bg-muted'
                        )}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                  <SourceNote source="落库(BaoStock/AkShare)" freshness="盘后/历史" />
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  <div className="flex items-center gap-1">
                    <span>主图</span>
                    {OVERLAYS.map((o) => (
                      <button
                        key={o.key}
                        type="button"
                        aria-pressed={overlay === o.key}
                        onClick={() => setOverlay(o.key)}
                        className={cn(
                          'rounded px-1.5 py-0.5 transition-colors',
                          overlay === o.key ? 'bg-muted text-foreground' : 'hover:text-foreground'
                        )}
                      >
                        {o.label}
                      </button>
                    ))}
                  </div>
                  <div className="flex items-center gap-1">
                    <span>副图</span>
                    {SUBS.map((s) => (
                      <button
                        key={s.key}
                        type="button"
                        aria-pressed={sub === s.key}
                        onClick={() => setSub(s.key)}
                        className={cn(
                          'rounded px-1.5 py-0.5 transition-colors',
                          sub === s.key ? 'bg-muted text-foreground' : 'hover:text-foreground'
                        )}
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {klineQuality === 'invalid_ohlc' && (
                  <p className="mb-3 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-700">
                    部分异常 K 线已隔离，当前图表仅展示通过 OHLC 校验的数据。
                  </p>
                )}
                {klineLoading ? (
                  <div className="flex h-[460px] items-center justify-center text-muted-foreground">
                    加载 K 线…
                  </div>
                ) : kline.length > 0 ? (
                  <div data-testid="stock-kline-chart">
                    <CandlestickChart data={kline} overlay={overlay} sub={sub} height={460} />
                  </div>
                ) : (
                  <div className="flex h-[460px] flex-col items-center justify-center gap-3 text-muted-foreground">
                    <p className="text-sm">
                      暂无{period === 'day' ? '日' : '分钟'}K线数据
                      {period !== 'day' && '（分钟K需 BaoStock 落库）'}
                    </p>
                    <Button size="sm" variant="outline" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
                      <RefreshCw className={cn('mr-1.5 h-3.5 w-3.5', refresh.isPending && 'animate-spin')} />
                      拉取并落库
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* 数据面板 */}
            <Card>
              <CardHeader className="pb-2">
                <div className="flex flex-wrap items-center gap-1">
                  {PANELS.map((p) => (
                    <button
                      key={p.key}
                      onClick={() => setPanel(p.key)}
                      className={cn(
                        'rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                        panel === p.key
                          ? 'bg-brand text-brand-foreground'
                          : 'text-muted-foreground hover:bg-muted'
                      )}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </CardHeader>
              <CardContent className="text-sm">
                {panel === 'overview' && (
                  <div>
                    <div className="mb-3 flex justify-end">
                      <SourceNote source="东方财富" freshness="盘后" limited={!profile?.industry} />
                    </div>
                    {profile && (profile.industry || profile.totalMarketCap) ? (
                      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
                        <Field label="所属行业" value={profile.industry ?? '—'} />
                        <Field label="上市日期" value={profile.listDate ?? '—'} />
                        <Field label="总市值" value={formatAmount(profile.totalMarketCap)} />
                        <Field label="流通市值" value={formatAmount(profile.floatMarketCap)} />
                        <Field label="总股本" value={formatAmount(profile.totalShares)} />
                        <Field label="流通股" value={formatAmount(profile.floatShares)} />
                      </dl>
                    ) : (
                      <Empty text="暂无概览数据（免费源可能限流，稍后重试或点击『刷新数据』）" />
                    )}
                  </div>
                )}

                {panel === 'capital' && (
                  <PanelTable
                    note={<SourceNote source="东方财富·资金流" freshness="盘后" limited={capitalFlow.length === 0} />}
                    empty={capitalFlow.length === 0}
                    head={['日期', '主力净额', '主力净占比', '超大单', '大单']}
                    rows={capitalFlow.map((r) => [
                      r.date,
                      <span key="m" className={changeClass(r.mainNet)}>{formatAmount(r.mainNet)}</span>,
                      <span key="r" className={changeClass(r.mainNetRatio)}>{r.mainNetRatio != null ? `${r.mainNetRatio.toFixed(2)}%` : '—'}</span>,
                      formatAmount(r.superLargeNet),
                      formatAmount(r.largeNet),
                    ])}
                  />
                )}

                {panel === 'financial' && (
                  <PanelTable
                    note={<SourceNote source="同花顺·按报告期" freshness="盘后" limited={financials.length === 0} />}
                    empty={financials.length === 0}
                    head={['报告期', 'EPS', 'BPS', 'ROE', '营收', '净利润']}
                    rows={financials.map((r) => [
                      r.reportDate,
                      r.eps != null ? r.eps.toFixed(2) : '—',
                      r.bps != null ? r.bps.toFixed(2) : '—',
                      r.roe != null ? `${r.roe.toFixed(2)}%` : '—',
                      formatAmount(r.revenue),
                      formatAmount(r.netProfit),
                    ])}
                  />
                )}

                {panel === 'lhb' && (
                  <PanelTable
                    note={<SourceNote source="东方财富·龙虎榜" freshness="盘后" limited={dragonTiger.length === 0} />}
                    empty={dragonTiger.length === 0}
                    emptyText="暂无龙虎榜记录（龙虎榜需按日期范围全市场落库）"
                    head={['日期', '上榜原因', '净买额', '买入', '卖出']}
                    rows={dragonTiger.map((r) => [
                      r.date,
                      <span key="reason" className="text-xs">{r.reason}</span>,
                      <span key="n" className={changeClass(r.netBuy)}>{formatAmount(r.netBuy)}</span>,
                      formatAmount(r.buy),
                      formatAmount(r.sell),
                    ])}
                  />
                )}

                {panel === 'news' && (
                  <div>
                    <div className="mb-3 flex justify-end">
                      <SourceNote source="东方财富·新闻" freshness="来源有限" limited={news.length === 0} />
                    </div>
                    {news.length > 0 ? (
                      <ul className="divide-y divide-border">
                        {news.map((n, i) => (
                          <li key={i} className="py-3">
                            <a
                              href={n.url ?? '#'}
                              target="_blank"
                              rel="noreferrer"
                              className="font-medium hover:text-brand"
                            >
                              {n.title}
                            </a>
                            <div className="mt-1 flex gap-3 text-xs text-muted-foreground">
                              {n.source && <span>{n.source}</span>}
                              {n.publishedAt && <span>{n.publishedAt.replace('T', ' ').slice(0, 16)}</span>}
                            </div>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <Empty text="暂无新闻（免费源可能限流，点击『刷新数据』重试）" />
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          {/* 右：嵌入式 AI 助手 */}
          <div className="lg:col-span-1">
            <Card className="lg:sticky lg:top-6 flex h-[640px] flex-col overflow-hidden">
              <CardHeader className="border-b border-border pb-3">
                <CardTitle className="text-base">AI 看盘助手</CardTitle>
                <p className="mt-1 text-xs text-muted-foreground">
                  侧栏为轻量问答；深度研究 / 记忆偏好请前往{' '}
                  <Link href="/ai" className="text-brand underline-offset-2 hover:underline">
                    AI 问答
                  </Link>
                  。
                </p>
              </CardHeader>
              <CardContent className="flex-1 overflow-hidden p-0">
                <ChatPanel
                  compact
                  contextHint={contextHint}
                  placeholder={`问问 ${q?.name || canonical}…`}
                  suggestions={[
                    '当前价格和涨跌幅？',
                    '最近资金流如何？',
                    '财务摘要怎么样？',
                    '所属什么板块？',
                  ]}
                />
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
      )}
    </RequireAuth>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="py-10 text-center text-sm text-muted-foreground">{text}</div>;
}

function PanelTable({
  note,
  head,
  rows,
  empty,
  emptyText = '暂无数据（点击『刷新数据』尝试落库）',
}: {
  note: React.ReactNode;
  head: string[];
  rows: React.ReactNode[][];
  empty: boolean;
  emptyText?: string;
}) {
  return (
    <div>
      <div className="mb-3 flex justify-end">{note}</div>
      {empty ? (
        <Empty text={emptyText} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-xs text-muted-foreground">
                {head.map((h, i) => (
                  <th key={h} className={cn('py-2 font-medium', i === 0 ? 'text-left' : 'text-right')}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, ri) => (
                <tr key={ri} className="border-b border-border/60">
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className={cn('tnum py-2', ci === 0 ? 'text-left text-muted-foreground' : 'text-right')}
                    >
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
