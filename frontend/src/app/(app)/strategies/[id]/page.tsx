'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, Copy, FlaskConical, Pencil } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { strategyQueryKeys } from '@/components/strategy/query-keys';
import { strategiesApi } from '@/lib/api/strategies';
import { formatDate } from '@/lib/utils/format';
import { useAuthStore } from '@/stores/useAuthStore';

export default function StrategyDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? '';
  const router = useRouter();
  const queryClient = useQueryClient();
  const userId = useAuthStore((state) => state.user?.id);
  const strategy = useQuery({
    queryKey: strategyQueryKeys.detail(userId, id),
    queryFn: () => strategiesApi.getDetail(id),
    enabled: Boolean(id && userId),
  });

  const updateCached = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.detail(userId, id) }),
      queryClient.invalidateQueries({ queryKey: strategyQueryKeys.all(userId) }),
    ]);
  };
  const toggle = useMutation({
    mutationFn: (enable: boolean) =>
      enable ? strategiesApi.enable(id) : strategiesApi.disable(id),
    onSuccess: updateCached,
  });
  const duplicate = useMutation({
    mutationFn: () => strategiesApi.duplicate(id),
    onSuccess: async (copied) => {
      await queryClient.invalidateQueries({ queryKey: strategyQueryKeys.all(userId) });
      router.push(`/strategies/${copied.id}`);
    },
  });
  const remove = useMutation({
    mutationFn: () => strategiesApi.delete(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: strategyQueryKeys.all(userId) });
      router.push('/strategies');
    },
  });

  if (strategy.isLoading) {
    return <p className="p-10 text-center text-sm text-muted-foreground">加载策略中…</p>;
  }
  if (!strategy.data || strategy.isError) {
    return (
      <div className="p-10 text-center">
        <p className="text-sm text-destructive">策略不存在或无权访问。</p>
        <Button asChild variant="outline" className="mt-4">
          <Link href="/strategies">返回策略库</Link>
        </Button>
      </div>
    );
  }

  const item = strategy.data;
  const active = item.status === 'active';

  return (
    <div className="container mx-auto max-w-5xl space-y-5 p-6">
      <Link
        href="/strategies"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        返回策略库
      </Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-display text-3xl tracking-tight">{item.name}</h1>
            <span
              className={`rounded-full px-2 py-1 text-xs ${
                active
                  ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                  : 'bg-muted text-muted-foreground'
              }`}
            >
              {active ? '已启用' : item.status === 'draft' ? '草稿' : '已停用'}
            </span>
          </div>
          <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
            {item.description || '暂无策略说明'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="outline"
            onClick={() => toggle.mutate(!active)}
            disabled={toggle.isPending}
          >
            {active ? '停用' : '启用'}
          </Button>
          <Button
            variant="outline"
            onClick={() => duplicate.mutate()}
            disabled={duplicate.isPending}
          >
            <Copy />
            复制
          </Button>
          <Button asChild>
            <Link href={`/strategies/${id}/edit`}>
              <Pencil />
              编辑
            </Link>
          </Button>
        </div>
      </header>

      <div className="grid gap-5 md:grid-cols-[1fr_1.4fr]">
        <Card>
          <CardHeader>
            <CardTitle>策略档案</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">内置策略</p>
              <p className="mt-1 font-medium">{item.builtinType}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">分类</p>
              <p className="mt-1 font-medium">{item.category}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">创建时间</p>
              <p className="mt-1">{formatDate(item.createdAt)}</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">更新时间</p>
              <p className="mt-1">{formatDate(item.updatedAt)}</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>参数快照</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-3 sm:grid-cols-2">
              {Object.entries(item.params).map(([key, value]) => (
                <div key={key} className="rounded-xl border border-border bg-muted/20 p-4">
                  <dt className="text-xs text-muted-foreground">{key}</dt>
                  <dd className="mt-1 font-display text-2xl tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      </div>

      <Card className="border-brand/30 bg-brand-soft">
        <CardContent className="flex flex-wrap items-center justify-between gap-4 p-5">
          <div>
            <p className="font-medium">在回测工作台验证策略</p>
            <p className="mt-1 text-sm text-muted-foreground">
              从“已保存策略”下拉框选择本策略，即可预填类型与参数。
            </p>
          </div>
          <Button asChild>
            <Link href="/backtest">
              <FlaskConical />
              前往回测
            </Link>
          </Button>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button
          variant="destructive"
          onClick={() => {
            if (window.confirm('确定删除这个策略吗？此操作不可撤销。')) {
              remove.mutate();
            }
          }}
          disabled={remove.isPending}
        >
          删除策略
        </Button>
      </div>
    </div>
  );
}
