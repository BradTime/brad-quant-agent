'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Pause, Play, Plus } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { strategiesApi } from '@/lib/api/strategies';
import { formatDate } from '@/lib/utils/format';
import { pageAfterDeletingItem } from '@/components/strategy/strategy-list';
import { strategyQueryKeys } from '@/components/strategy/query-keys';
import { useAuthStore } from '@/stores/useAuthStore';
import type {
  BuiltinStrategyType,
  Strategy,
  StrategyListParams,
  StrategyStatus,
} from '@/types/strategy';

const BUILTIN_LABELS: Record<BuiltinStrategyType, string> = {
  dual_ma: '双均线',
  rsi: 'RSI 反转',
  boll: '布林带',
  momentum: '动量',
};

const CATEGORY_LABELS: Record<Strategy['category'], string> = {
  trend_following: '趋势跟随',
  mean_reversion: '均值回归',
  momentum: '动量',
};

const STATUS_LABELS: Record<
  StrategyStatus,
  { label: string; className: string }
> = {
  draft: {
    label: '草稿',
    className: 'bg-muted text-muted-foreground',
  },
  active: {
    label: '已启用',
    className: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
  },
  disabled: {
    label: '已停用',
    className: 'bg-amber-500/10 text-amber-700 dark:text-amber-400',
  },
};

export default function StrategiesPage() {
  const queryClient = useQueryClient();
  const userId = useAuthStore((state) => state.user?.id);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState<StrategyStatus | ''>('');
  const [builtinType, setBuiltinType] = useState<BuiltinStrategyType | ''>('');
  const [deleteTarget, setDeleteTarget] = useState<Strategy | null>(null);
  const pageSize = 10;

  const params: StrategyListParams = {
    page,
    pageSize,
    search: search || undefined,
    status: status || undefined,
    builtinType: builtinType || undefined,
    sortBy: 'updatedAt',
    sortOrder: 'desc',
  };
  const strategies = useQuery({
    queryKey: strategyQueryKeys.list(userId, params),
    queryFn: () => strategiesApi.getList(params),
    enabled: !!userId,
  });
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: strategyQueryKeys.all(userId) });

  const statusMutation = useMutation({
    mutationFn: ({ id, enable }: { id: string; enable: boolean }) =>
      enable ? strategiesApi.enable(id) : strategiesApi.disable(id),
    onSuccess: refresh,
  });
  const duplicateMutation = useMutation({
    mutationFn: strategiesApi.duplicate,
    onSuccess: refresh,
  });
  const deleteMutation = useMutation({
    mutationFn: strategiesApi.delete,
    onSuccess: () => {
      setPage((current) =>
        pageAfterDeletingItem(current, strategies.data?.items.length ?? 0),
      );
      refresh();
    },
  });

  const items = strategies.data?.items ?? [];
  const total = strategies.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const remove = (item: Strategy) => {
    setDeleteTarget(item);
  };

  return (
    <div className="container mx-auto space-y-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-brand">Strategy Library</p>
          <h1 className="mt-1 font-display text-3xl tracking-tight">策略管理</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            保存受约束的内置策略参数，随时载入回测工作台。
          </p>
        </div>
        <Button asChild>
          <Link href="/strategies/new">
            <Plus />
            新建策略
          </Link>
        </Button>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>筛选策略</CardTitle>
          <CardDescription>按名称、状态或内置策略类型查找</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-3">
          <Input
            aria-label="搜索策略"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder="搜索名称或说明"
          />
          <select
            aria-label="按状态筛选"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as StrategyStatus | '');
              setPage(1);
            }}
            className="h-10 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">全部状态</option>
            <option value="draft">草稿</option>
            <option value="active">已启用</option>
            <option value="disabled">已停用</option>
          </select>
          <select
            aria-label="按内置策略筛选"
            value={builtinType}
            onChange={(event) => {
              setBuiltinType(event.target.value as BuiltinStrategyType | '');
              setPage(1);
            }}
            className="h-10 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">全部内置策略</option>
            {Object.entries(BUILTIN_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>策略库</CardTitle>
          <CardDescription>共 {total} 个策略</CardDescription>
        </CardHeader>
        <CardContent>
          {strategies.isLoading ? (
            <p className="py-12 text-center text-sm text-muted-foreground">加载策略中…</p>
          ) : strategies.isError ? (
            <p className="py-12 text-center text-sm text-destructive">策略加载失败，请稍后重试。</p>
          ) : items.length === 0 ? (
            <div className="py-14 text-center">
              <p className="text-sm text-muted-foreground">当前筛选条件下没有策略。</p>
              <Button asChild variant="outline" className="mt-4">
                <Link href="/strategies/new">创建第一个策略</Link>
              </Button>
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>名称</TableHead>
                    <TableHead>内置策略</TableHead>
                    <TableHead>分类</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>更新时间</TableHead>
                    <TableHead className="text-right">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((item) => {
                    const statusMeta = STATUS_LABELS[item.status];
                    return (
                      <TableRow key={item.id}>
                        <TableCell>
                          <Link
                            href={`/strategies/${item.id}`}
                            className="font-medium hover:text-brand"
                          >
                            {item.name}
                          </Link>
                          {item.description && (
                            <p className="mt-1 max-w-xs truncate text-xs text-muted-foreground">
                              {item.description}
                            </p>
                          )}
                        </TableCell>
                        <TableCell>{BUILTIN_LABELS[item.builtinType]}</TableCell>
                        <TableCell>{CATEGORY_LABELS[item.category]}</TableCell>
                        <TableCell>
                          <span className={`rounded-full px-2 py-1 text-xs ${statusMeta.className}`}>
                            {statusMeta.label}
                          </span>
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDate(item.updatedAt)}
                        </TableCell>
                        <TableCell>
                          <div className="flex justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="icon"
                              title={item.status === 'active' ? '停用' : '启用'}
                              onClick={() =>
                                statusMutation.mutate({
                                  id: item.id,
                                  enable: item.status !== 'active',
                                })
                              }
                            >
                              {item.status === 'active' ? <Pause /> : <Play />}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              title="复制"
                              onClick={() => duplicateMutation.mutate(item.id)}
                            >
                              <Copy />
                            </Button>
                            <Button asChild variant="outline" size="sm">
                              <Link href={`/strategies/${item.id}/edit`}>编辑</Link>
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => remove(item)}
                            >
                              删除
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="mt-5 flex items-center justify-center gap-3">
                  <Button
                    variant="outline"
                    onClick={() => setPage((value) => Math.max(1, value - 1))}
                    disabled={page === 1}
                  >
                    上一页
                  </Button>
                  <span className="text-sm text-muted-foreground">
                    {page} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                    disabled={page >= totalPages}
                  >
                    下一页
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Dialog open={deleteTarget != null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认删除策略</DialogTitle>
            <DialogDescription>
              确定删除策略「{deleteTarget?.name}」吗？此操作不可撤销。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() => {
                if (deleteTarget) {
                  deleteMutation.mutate(deleteTarget.id, {
                    onSuccess: () => setDeleteTarget(null),
                  });
                }
              }}
            >
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
