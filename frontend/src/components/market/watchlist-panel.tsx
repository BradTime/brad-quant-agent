'use client';

import Link from 'next/link';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { Star, X } from 'lucide-react';
import { watchlistApi, type WatchlistItemView } from '@/lib/api/watchlist';
import { useAuthStore } from '@/stores/useAuthStore';
import { cn } from '@/lib/utils';
import { watchlistQueryKeys } from './watchlist-query-keys';

function changeClass(v: number | null): string {
  if (v === null || v === 0) return 'text-muted-foreground';
  return v > 0 ? 'text-up' : 'text-down';
}

export function WatchlistPanel() {
  const queryClient = useQueryClient();
  const userId = useAuthStore((s) => s.user?.id);

  const { data: items = [], isLoading } = useQuery({
    queryKey: watchlistQueryKeys.all(userId),
    queryFn: () => watchlistApi.getList(),
    enabled: Boolean(userId),
    refetchInterval: 8000,
    retry: false,
  });

  const remove = useMutation({
    mutationFn: (code: string) => watchlistApi.remove(code),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: watchlistQueryKeys.all(userId) }),
  });

  const groups = items.reduce<Record<string, WatchlistItemView[]>>((acc, it) => {
    (acc[it.group] ||= []).push(it);
    return acc;
  }, {});
  const groupNames = Object.keys(groups);

  return (
    <div>
      {isLoading ? (
        <div className="py-8 text-center text-sm text-muted-foreground">加载中…</div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-10 text-center">
          <Star className="h-6 w-6 text-muted-foreground/50" />
          <p className="text-sm text-muted-foreground">还没有自选股</p>
          <p className="text-xs text-muted-foreground">用上方搜索框找到个股，进入详情页点「加自选」</p>
        </div>
      ) : (
        <div className="space-y-4">
          {groupNames.map((g) => (
            <div key={g}>
              <div className="mb-1.5 px-1 text-xs font-medium text-muted-foreground">{g}</div>
              <ul className="space-y-0.5">
                {groups[g].map((it) => (
                  <li key={it.code} className="group flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-muted/60">
                    <Link href={`/market/${encodeURIComponent(it.code)}`} className="flex flex-1 items-center justify-between">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium">{it.name || it.code}</div>
                        <div className="font-mono text-[10px] text-muted-foreground">{it.code}</div>
                      </div>
                      <div className="text-right">
                        <div className={cn('tnum text-sm font-semibold', changeClass(it.change))}>
                          {it.price != null ? it.price.toFixed(2) : '—'}
                        </div>
                        <div className={cn('tnum text-[11px]', changeClass(it.change))}>
                          {it.changePercent != null
                            ? `${it.changePercent >= 0 ? '+' : ''}${it.changePercent.toFixed(2)}%`
                            : '—'}
                        </div>
                      </div>
                    </Link>
                    <button
                      onClick={() => remove.mutate(it.code)}
                      className="opacity-0 transition-opacity group-hover:opacity-100"
                      aria-label="移除"
                    >
                      <X className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
