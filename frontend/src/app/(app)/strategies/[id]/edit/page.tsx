'use client';

import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft } from 'lucide-react';
import { StrategyForm } from '@/components/strategy/strategy-form';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { strategiesApi } from '@/lib/api/strategies';
import type { StrategyCreateRequest } from '@/types/strategy';

export default function EditStrategyPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? '';
  const router = useRouter();
  const queryClient = useQueryClient();
  const strategy = useQuery({
    queryKey: ['strategy', id],
    queryFn: () => strategiesApi.getDetail(id),
    enabled: Boolean(id),
  });
  const update = useMutation({
    mutationFn: (data: StrategyCreateRequest) =>
      strategiesApi.update({ id, ...data }),
  });

  const save = async (data: StrategyCreateRequest) => {
    await update.mutateAsync(data);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['strategy', id] }),
      queryClient.invalidateQueries({ queryKey: ['strategies'] }),
    ]);
    router.push(`/strategies/${id}`);
  };

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

  return (
    <div className="container mx-auto max-w-4xl space-y-5 p-6">
      <Link
        href={`/strategies/${id}`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        返回策略详情
      </Link>
      <Card>
        <CardHeader>
          <p className="text-xs uppercase tracking-[0.2em] text-brand">Edit Strategy</p>
          <CardTitle className="font-display text-2xl">编辑策略配置</CardTitle>
          <p className="text-sm text-muted-foreground">
            切换内置策略时，参数会重置为该策略的目录默认值。
          </p>
        </CardHeader>
        <CardContent>
          <StrategyForm
            initial={strategy.data}
            submitLabel="保存修改"
            submitting={update.isPending}
            onSubmit={save}
          />
        </CardContent>
      </Card>
    </div>
  );
}
