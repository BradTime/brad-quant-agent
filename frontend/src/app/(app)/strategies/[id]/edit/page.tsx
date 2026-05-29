'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { RequireAuth } from '@/components/auth/require-auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { strategiesApi } from '@/lib/api/strategies';
import type { StrategyUpdateRequest } from '@/types/strategy';

const strategySchema = z.object({
  name: z.string().min(1, '策略名称不能为空').max(100, '策略名称不能超过100个字符'),
  description: z.string().max(500, '描述不能超过500个字符').optional(),
  type: z.enum(['trend_following', 'mean_reversion', 'arbitrage', 'momentum', 'other']),
  code: z.string().optional(),
});

type StrategyFormData = z.infer<typeof strategySchema>;

export default function EditStrategyPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const strategyId = params?.id ?? '';
  const queryClient = useQueryClient();

  const { data: strategy, isLoading } = useQuery({
    queryKey: ['strategy', strategyId],
    queryFn: () => strategiesApi.getDetail(strategyId),
    enabled: !!strategyId,
  });

  const {
    register,
    handleSubmit,
    formState: { errors },
    reset,
  } = useForm<StrategyFormData>({
    resolver: zodResolver(strategySchema),
  });

  useEffect(() => {
    if (strategy) {
      reset({
        name: strategy.name,
        description: strategy.description || '',
        type: strategy.type,
        code: strategy.code || '',
      });
      setParamsJson(JSON.stringify(strategy.params, null, 2));
    }
  }, [strategy, reset]);

  const [paramsJson, setParamsJson] = useState('{}');

  const updateMutation = useMutation({
    mutationFn: (data: StrategyUpdateRequest) => strategiesApi.update(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['strategy', strategyId] });
      queryClient.invalidateQueries({ queryKey: ['strategies'] });
      router.push(`/strategies/${strategyId}`);
    },
  });

  const onSubmit = (data: StrategyFormData) => {
    try {
      const params = paramsJson ? JSON.parse(paramsJson) : {};
      updateMutation.mutate({
        id: strategyId,
        ...data,
        params,
      });
    } catch {
      alert('参数 JSON 格式错误，请检查后重试');
    }
  };

  if (isLoading) {
    return (
      <RequireAuth>
        <div className="container mx-auto p-6">
          <div className="text-center py-8">加载中...</div>
        </div>
      </RequireAuth>
    );
  }

  if (!strategy) {
    return (
      <RequireAuth>
        <div className="container mx-auto p-6">
          <div className="text-center py-8">
            <p className="text-muted-foreground">策略不存在</p>
            <Link href="/strategies">
              <Button className="mt-4">返回策略列表</Button>
            </Link>
          </div>
        </div>
      </RequireAuth>
    );
  }

  return (
    <RequireAuth>
      <div className="container mx-auto p-6 max-w-4xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold">编辑策略</h1>
          <p className="text-muted-foreground">修改策略信息</p>
        </div>

        <form onSubmit={handleSubmit(onSubmit)}>
          <Card>
            <CardHeader>
              <CardTitle>基本信息</CardTitle>
              <CardDescription>修改策略的基本信息</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">策略名称 *</Label>
                <Input id="name" {...register('name')} />
                {errors.name && (
                  <p className="text-sm text-red-500">{errors.name.message}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">策略描述</Label>
                <Textarea
                  id="description"
                  {...register('description')}
                  rows={3}
                />
                {errors.description && (
                  <p className="text-sm text-red-500">{errors.description.message}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="type">策略类型 *</Label>
                <select
                  id="type"
                  {...register('type')}
                  className="w-full px-3 py-2 border rounded-md"
                >
                  <option value="trend_following">趋势跟踪</option>
                  <option value="mean_reversion">均值回归</option>
                  <option value="arbitrage">套利</option>
                  <option value="momentum">动量</option>
                  <option value="other">其他</option>
                </select>
                {errors.type && (
                  <p className="text-sm text-red-500">{errors.type.message}</p>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="mt-6">
            <CardHeader>
              <CardTitle>策略参数</CardTitle>
              <CardDescription>以 JSON 格式配置策略参数</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="params">参数 JSON</Label>
                <Textarea
                  id="params"
                  value={paramsJson}
                  onChange={(e) => setParamsJson(e.target.value)}
                  rows={6}
                  className="font-mono text-sm"
                />
              </div>
            </CardContent>
          </Card>

          <Card className="mt-6">
            <CardHeader>
              <CardTitle>策略代码（可选）</CardTitle>
              <CardDescription>修改策略的具体实现代码</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="code">代码</Label>
                <Textarea
                  id="code"
                  {...register('code')}
                  rows={10}
                  className="font-mono text-sm"
                />
                {errors.code && (
                  <p className="text-sm text-red-500">{errors.code.message}</p>
                )}
              </div>
            </CardContent>
          </Card>

          <div className="flex gap-4 mt-6">
            <Button type="submit" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? '保存中...' : '保存修改'}
            </Button>
            <Link href={`/strategies/${strategyId}`}>
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

