'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft } from 'lucide-react';
import { StrategyForm } from '@/components/strategy/strategy-form';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { strategiesApi } from '@/lib/api/strategies';
import type { StrategyCreateRequest } from '@/types/strategy';

export default function NewStrategyPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const create = useMutation({ mutationFn: strategiesApi.create });

  const save = async (data: StrategyCreateRequest) => {
    const strategy = await create.mutateAsync(data);
    await queryClient.invalidateQueries({ queryKey: ['strategies'] });
    router.push(`/strategies/${strategy.id}`);
  };

  return (
    <div className="container mx-auto max-w-4xl space-y-5 p-6">
      <Link
        href="/strategies"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        返回策略库
      </Link>
      <Card>
        <CardHeader>
          <p className="text-xs uppercase tracking-[0.2em] text-brand">New Strategy</p>
          <CardTitle className="font-display text-2xl">创建内置策略配置</CardTitle>
          <p className="text-sm text-muted-foreground">
            只保存受支持的参数，不接收或执行自定义 Python 代码。
          </p>
        </CardHeader>
        <CardContent>
          <StrategyForm
            submitLabel="保存策略"
            submitting={create.isPending}
            onSubmit={save}
          />
        </CardContent>
      </Card>
    </div>
  );
}
