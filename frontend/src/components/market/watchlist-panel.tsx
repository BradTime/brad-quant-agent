'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { ChevronDown, ChevronUp, Pencil, Star, X } from 'lucide-react';
import { watchlistApi, type WatchlistItemView } from '@/lib/api/watchlist';
import { useAuthStore } from '@/stores/useAuthStore';
import { cn } from '@/lib/utils';
import { watchlistQueryKeys } from './watchlist-query-keys';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

function changeClass(v: number | null): string {
  if (v === null || v === 0) return 'text-muted-foreground';
  return v > 0 ? 'text-up' : 'text-down';
}

function groupItems(items: WatchlistItemView[]): Record<string, WatchlistItemView[]> {
  return items.reduce<Record<string, WatchlistItemView[]>>((acc, it) => {
    (acc[it.group] ||= []).push(it);
    return acc;
  }, {});
}

export function WatchlistPanel() {
  const queryClient = useQueryClient();
  const userId = useAuthStore((s) => s.user?.id);
  const [editingGroup, setEditingGroup] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState('');

  const { data: items = [], isLoading } = useQuery({
    queryKey: watchlistQueryKeys.all(userId),
    queryFn: () => watchlistApi.getList(),
    enabled: Boolean(userId),
    refetchInterval: 8000,
    retry: false,
  });

  const { data: groups = ['默认分组'] } = useQuery({
    queryKey: watchlistQueryKeys.groups(userId),
    queryFn: () => watchlistApi.getGroups(),
    enabled: Boolean(userId),
    retry: false,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: watchlistQueryKeys.all(userId) });
    queryClient.invalidateQueries({ queryKey: watchlistQueryKeys.groups(userId) });
  };

  const remove = useMutation({
    mutationFn: (code: string) => watchlistApi.remove(code),
    onSuccess: invalidate,
  });

  const update = useMutation({
    mutationFn: ({ code, body }: { code: string; body: { group?: string; sortOrder?: number } }) =>
      watchlistApi.update(code, body),
    onSuccess: invalidate,
  });

  const grouped = groupItems(items);
  const groupNames = Object.keys(grouped).sort();

  const sortedInGroup = (g: string) =>
    [...(grouped[g] ?? [])].sort((a, b) => a.sortOrder - b.sortOrder || a.code.localeCompare(b.code));

  const moveItem = (item: WatchlistItemView, dir: 'up' | 'down') => {
    const list = sortedInGroup(item.group);
    const idx = list.findIndex((i) => i.code === item.code);
    const swapIdx = dir === 'up' ? idx - 1 : idx + 1;
    if (swapIdx < 0 || swapIdx >= list.length) return;
    const other = list[swapIdx];
    update.mutate({ code: item.code, body: { sortOrder: other.sortOrder } });
    update.mutate({ code: other.code, body: { sortOrder: item.sortOrder } });
  };

  const renameGroup = (oldName: string) => {
    const next = renameDraft.trim();
    setEditingGroup(null);
    if (!next || next === oldName) return;
    for (const it of grouped[oldName] ?? []) {
      update.mutate({ code: it.code, body: { group: next } });
    }
  };

  const moveOptions = [...new Set([...groups, ...groupNames, '默认分组'])].sort();

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
              <div className="mb-1.5 flex items-center gap-1 px-1">
                {editingGroup === g ? (
                  <Input
                    autoFocus
                    value={renameDraft}
                    onChange={(e) => setRenameDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') renameGroup(g);
                      if (e.key === 'Escape') setEditingGroup(null);
                    }}
                    onBlur={() => renameGroup(g)}
                    className="h-7 max-w-[140px] text-xs"
                  />
                ) : (
                  <>
                    <span className="text-xs font-medium text-muted-foreground">{g}</span>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6"
                      aria-label="重命名分组"
                      onClick={() => {
                        setEditingGroup(g);
                        setRenameDraft(g);
                      }}
                    >
                      <Pencil className="h-3 w-3 text-muted-foreground" />
                    </Button>
                  </>
                )}
              </div>
              <ul className="space-y-0.5">
                {sortedInGroup(g).map((it, idx, list) => (
                  <li
                    key={it.code}
                    className="group flex items-center gap-1 rounded-lg px-2 py-1.5 hover:bg-muted/60"
                  >
                    <Link
                      href={`/market/${encodeURIComponent(it.code)}`}
                      className="flex min-w-0 flex-1 items-center justify-between"
                    >
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
                    <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                      <Select
                        value={it.group}
                        onValueChange={(next) =>
                          update.mutate({ code: it.code, body: { group: next } })
                        }
                      >
                        <SelectTrigger className="h-7 w-[72px] px-1.5 text-[10px]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {moveOptions.map((name) => (
                            <SelectItem key={name} value={name} className="text-xs">
                              {name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        disabled={idx === 0}
                        aria-label="上移"
                        onClick={() => moveItem(it, 'up')}
                      >
                        <ChevronUp className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        disabled={idx === list.length - 1}
                        aria-label="下移"
                        onClick={() => moveItem(it, 'down')}
                      >
                        <ChevronDown className="h-3.5 w-3.5" />
                      </Button>
                      <button
                        onClick={() => remove.mutate(it.code)}
                        aria-label="移除"
                      >
                        <X className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
                      </button>
                    </div>
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
