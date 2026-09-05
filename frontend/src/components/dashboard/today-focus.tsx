'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { getLatestBrief } from '@/lib/api/brief';
import { marketApi } from '@/lib/api/market';
import { watchlistApi } from '@/lib/api/watchlist';
import { watchlistQueryKeys } from '@/components/market/watchlist-query-keys';
import { useAuthStore } from '@/stores/useAuthStore';
import { cn } from '@/lib/utils';

function changeClass(value: number | null): string {
  if (value === null || value === 0) return 'text-muted-foreground';
  return value > 0 ? 'text-up' : 'text-down';
}

function formatAge(ms: number | null | undefined): string {
  if (ms == null) return '缓存暂无';
  if (ms < 5_000) return '缓存刚刚更新';
  if (ms < 60_000) return `缓存 ${Math.round(ms / 1000)} 秒前`;
  return `缓存 ${Math.round(ms / 60_000)} 分钟前`;
}

/**
 * 驾驶舱「今日关注」：早报 → 自选 → 个股 / AI / 回测 / 模拟。
 */
export function TodayFocus({ className }: { className?: string }) {
  const userId = useAuthStore((state) => state.user?.id);

  const { data: brief } = useQuery({
    queryKey: ['brief', 'latest'],
    queryFn: () => getLatestBrief(),
    enabled: Boolean(userId),
    staleTime: 60_000,
  });

  const { data: watchlist = [] } = useQuery({
    queryKey: watchlistQueryKeys.all(userId),
    queryFn: () => watchlistApi.getList(),
    enabled: Boolean(userId),
  });

  const { data: freshness } = useQuery({
    queryKey: ['market', 'freshness'],
    queryFn: () => marketApi.getFreshness(),
    refetchInterval: 30_000,
  });

  const top = watchlist.slice(0, 8);
  const lastIngestion = freshness?.lastIngestion;
  const eodJob = freshness?.jobs?.watchlist_eod_backfill;

  return (
    <Card className={cn(className)} data-testid="today-focus">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <CardTitle>今日关注</CardTitle>
            <CardDescription>
              早报 → 自选 → 个股 / AI / 回测 / 模拟
            </CardDescription>
          </div>
          <Button asChild variant="outline" size="sm">
            <Link href="/brief">{brief ? '打开早报' : '去早报页'}</Link>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm">
          {brief ? (
            <p>
              <span className="text-muted-foreground">最新早报 · </span>
              <Link href="/brief" className="font-medium text-foreground hover:underline">
                {brief.title || `${brief.tradeDate ?? ''} 盘前早报`}
              </Link>
            </p>
          ) : (
            <p className="text-muted-foreground">暂无早报，可前往生成今日早报。</p>
          )}
          <p className="mt-1 text-xs text-muted-foreground">
            {formatAge(freshness?.quotesAgeMs)}
            {lastIngestion
              ? ` · 最近回填 ${lastIngestion.code}（${lastIngestion.status}）`
              : ''}
            {eodJob?.successAgeSeconds != null
              ? ` · EOD 任务 ${Math.round(eodJob.successAgeSeconds)}s 前成功`
              : ''}
          </p>
        </div>

        {top.length === 0 ? (
          <p className="text-sm text-muted-foreground" data-testid="today-focus-empty">
            自选股为空。去{' '}
            <Link href="/market" className="underline">
              看盘
            </Link>{' '}
            添加关注标的后，这里会串起后续操作。
          </p>
        ) : (
          <ul className="divide-y divide-border" data-testid="today-focus-list">
            {top.map((item) => (
              <li
                key={item.code}
                className="flex flex-wrap items-center justify-between gap-2 py-2.5"
              >
                <Link
                  href={`/market/${encodeURIComponent(item.code)}`}
                  className="min-w-0 flex-1 hover:underline"
                >
                  <span className="font-mono text-sm">{item.code}</span>
                  <span className="ml-2 text-sm font-medium">{item.name || '—'}</span>
                  <span className={cn('ml-2 text-xs tabular-nums', changeClass(item.changePercent))}>
                    {item.changePercent == null
                      ? ''
                      : `${item.changePercent >= 0 ? '+' : ''}${item.changePercent.toFixed(2)}%`}
                  </span>
                </Link>
                <div className="flex flex-wrap gap-1.5">
                  <Button asChild variant="ghost" size="sm" className="h-7 px-2 text-xs">
                    <Link href={`/ai?code=${encodeURIComponent(item.code)}`}>AI</Link>
                  </Button>
                  <Button asChild variant="ghost" size="sm" className="h-7 px-2 text-xs">
                    <Link href={`/backtest?code=${encodeURIComponent(item.code)}`}>回测</Link>
                  </Button>
                  <Button asChild variant="ghost" size="sm" className="h-7 px-2 text-xs">
                    <Link href={`/sim?code=${encodeURIComponent(item.code)}`}>模拟</Link>
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
