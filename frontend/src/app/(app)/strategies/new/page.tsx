'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useMutation } from '@tanstack/react-query';
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
import type { StrategyCreateRequest } from '@/types/strategy';

const strategySchema = z.object({
  name: z.string().min(1, '策略名称不能为空').max(100, '策略名称不能超过100个字符'),
  description: z.string().max(500, '描述不能超过500个字符').optional(),
  type: z.enum(['trend_following', 'mean_reversion', 'arbitrage', 'momentum', 'other']),
  code: z.string().optional(),
});

type StrategyFormData = z.infer<typeof strategySchema>;

export default function NewStrategyPage() {
  const router = useRouter();
  const [paramsJson, setParamsJson] = useState('{}');

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<StrategyFormData>({
    resolver: zodResolver(strategySchema),
    defaultValues: {
      type: 'trend_following',
    },
  });

  const createMutation = useMutation({
    mutationFn: (data: StrategyCreateRequest) => strategiesApi.create(data),
    onSuccess: (strategy) => {
      router.push(`/strategies/${strategy.id}`);
    },
  });

  const onSubmit = (data: StrategyFormData) => {
    try {
      const params = paramsJson ? JSON.parse(paramsJson) : {};
      createMutation.mutate({
        ...data,
        params,
      });
    } catch {
      alert('参数 JSON 格式错误，请检查后重试');
    }
  };


  return (
    <RequireAuth>
      <div className="container mx-auto p-6 max-w-4xl">
        <div className="mb-6">
          <h1 className="text-3xl font-bold">创建策略</h1>
          <p className="text-muted-foreground">创建新的量化投资策略</p>
        </div>

        <Card className="mb-6 border-brand/30 bg-brand-soft">
          <CardContent className="p-4 text-sm text-muted-foreground">
            策略创建将在 Phase 4 量化研究阶段开放。当前页面保留为设计占位，提交已禁用，避免产生无效请求。
          </CardContent>
        </Card>

        <form onSubmit={handleSubmit(onSubmit)}>
          <Card>
            <CardHeader>
              <CardTitle>基本信息</CardTitle>
              <CardDescription>填写策略的基本信息</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">策略名称 *</Label>
                <Input
                  id="name"
                  {...register('name')}
                  placeholder="例如：双均线策略"
                />
                {errors.name && (
                  <p className="text-sm text-red-500">{errors.name.message}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">策略描述</Label>
                <Textarea
                  id="description"
                  {...register('description')}
                  placeholder="描述策略的思路和特点..."
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
                  placeholder='例如：{"fast_period": 5, "slow_period": 20}'
                  rows={6}
                  className="font-mono text-sm"
                />
                <p className="text-sm text-muted-foreground">
                  请输入有效的 JSON 格式参数
                </p>
              </div>
            </CardContent>
          </Card>

          <Card className="mt-6">
            <CardHeader>
              <CardTitle>策略代码（可选）</CardTitle>
              <CardDescription>输入策略的具体实现代码</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="code">代码</Label>
                <Textarea
                  id="code"
                  {...register('code')}
                  placeholder="def strategy(context):&#10;    # 策略代码..."
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
            <Button type="submit" disabled>
              创建策略（Phase 4）
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

