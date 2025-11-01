'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useQuery, useMutation } from '@tanstack/react-query';
import Link from 'next/link';
import { RequireAuth } from '@/components/auth/require-auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { backtestApi } from '@/lib/api/backtest';
import { strategiesApi } from '@/lib/api/strategies';
import type { BacktestConfig } from '@/types/backtest';

const backtestSchema = z.object({
  strategyId: z.string().min(1, '请选择策略'),
  startDate: z.string().min(1, '请选择开始日期'),
  endDate: z.string().min(1, '请选择结束日期'),
  initialCapital: z.number().min(1000, '初始资金至少为1000元'),
  commission: z.number().min(0).max(1, '手续费率应在0-1之间'),
  slippage: z.number().min(0).max(1, '滑点应在0-1之间'),
});

type BacktestFormData = z.infer<typeof backtestSchema>;

export default function NewBacktestPage() {
  const router = useRouter();
  const [dataSource, setDataSource] = useState('');

  const { data: strategies } = useQuery({
    queryKey: ['strategies', 'all'],
    queryFn: () => strategiesApi.getList({ pageSize: 100 }),
  });

  const {
    register,
    handleSubmit,
    formState: { errors },
    watch,
  } = useForm<BacktestFormData>({
    resolver: zodResolver(backtestSchema),
    defaultValues: {
      initialCapital: 100000,
      commission: 0.001,
      slippage: 0.001,
    },
  });

  const runMutation = useMutation({
    mutationFn: (config: BacktestConfig) => backtestApi.run(config),
    onSuccess: (result) => {
      router.push(`/backtest/${result.id}`);
    },
  });

  const onSubmit = (data: BacktestFormData) => {
    runMutation.mutate({
      ...data,
      dataSource: dataSource || undefined,
    });
  };

  const startDate = watch('startDate');
  const endDate = watch('endDate');

  const strategyOptions = strategies?.data?.items || [];

  return (
    <RequireAuth>
      <div className="container mx-auto p-6 max-w-4xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold">执行回测</h1>
          <p className="text-muted-foreground">配置回测参数并执行回测分析</p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)}>
          <Card>
            <CardHeader>
              <CardTitle>回测配置</CardTitle>
              <CardDescription>设置回测的基本参数</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="strategyId">选择策略 *</Label>
                <select
                  id="strategyId"
                  {...register('strategyId')}
                  className="w-full px-3 py-2 border rounded-md"
                >
                  <option value="">请选择策略</option>
                  {strategyOptions.map((strategy) => (
                    <option key={strategy.id} value={strategy.id}>
                      {strategy.name}
                    </option>
                  ))}
                </select>
                {errors.strategyId && (
                  <p className="text-sm text-red-500">{errors.strategyId.message}</p>
                )}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="startDate">开始日期 *</Label>
                  <Input
                    id="startDate"
                    type="date"
                    {...register('startDate')}
                    max={endDate || undefined}
                  />
                  {errors.startDate && (
                    <p className="text-sm text-red-500">{errors.startDate.message}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="endDate">结束日期 *</Label>
                  <Input
                    id="endDate"
                    type="date"
                    {...register('endDate')}
                    min={startDate || undefined}
                  />
                  {errors.endDate && (
                    <p className="text-sm text-red-500">{errors.endDate.message}</p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="initialCapital">初始资金（元）*</Label>
                <Input
                  id="initialCapital"
                  type="number"
                  step="1000"
                  {...register('initialCapital', { valueAsNumber: true })}
                />
                {errors.initialCapital && (
                  <p className="text-sm text-red-500">{errors.initialCapital.message}</p>
                )}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="commission">手续费率 *</Label>
                  <Input
                    id="commission"
                    type="number"
                    step="0.0001"
                    {...register('commission', { valueAsNumber: true })}
                  />
                  <p className="text-sm text-muted-foreground">例如：0.001 表示 0.1%</p>
                  {errors.commission && (
                    <p className="text-sm text-red-500">{errors.commission.message}</p>
                  )}
                </div>

                <div className="space-y-2">
                  <Label htmlFor="slippage">滑点 *</Label>
                  <Input
                    id="slippage"
                    type="number"
                    step="0.0001"
                    {...register('slippage', { valueAsNumber: true })}
                  />
                  <p className="text-sm text-muted-foreground">例如：0.001 表示 0.1%</p>
                  {errors.slippage && (
                    <p className="text-sm text-red-500">{errors.slippage.message}</p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="dataSource">数据源（可选）</Label>
                <Input
                  id="dataSource"
                  value={dataSource}
                  onChange={(e) => setDataSource(e.target.value)}
                  placeholder="留空使用默认数据源"
                />
              </div>
            </CardContent>
          </Card>

          <div className="flex gap-4 mt-6">
            <Button type="submit" disabled={runMutation.isPending}>
              {runMutation.isPending ? '执行中...' : '执行回测'}
            </Button>
            <Link href="/strategies">
              <Button type="button" variant="outline">
                取消
              </Button>
            </Link>
          </div>
        </form>
      </div>
    </RequireAuth>
  );
}


