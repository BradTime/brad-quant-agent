'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { RequireAuth } from '@/components/auth/require-auth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { strategiesApi } from '@/lib/api/strategies';
import type { Strategy, StrategyListParams } from '@/types/strategy';
import { formatPercent, formatDate } from '@/lib/utils/format';

const STRATEGY_TYPE_MAP: Record<Strategy['type'], string> = {
  trend_following: '趋势跟踪',
  mean_reversion: '均值回归',
  arbitrage: '套利',
  momentum: '动量',
  other: '其他',
};

const STRATEGY_STATUS_MAP: Record<Strategy['status'], { label: string; className: string }> = {
  draft: { label: '草稿', className: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200' },
  active: { label: '运行中', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
  paused: { label: '已暂停', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
  stopped: { label: '已停止', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
};

export default function StrategiesPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<Strategy['status'] | 'all'>('all');
  const [typeFilter, setTypeFilter] = useState<Strategy['type'] | 'all'>('all');

  const params: StrategyListParams = {
    page,
    pageSize,
    ...(search && { search }),
    ...(statusFilter !== 'all' && { status: statusFilter }),
    ...(typeFilter !== 'all' && { type: typeFilter }),
    sortBy: 'updatedAt',
    sortOrder: 'desc',
  };

  const { data, isLoading } = useQuery({
    queryKey: ['strategies', params],
    queryFn: () => strategiesApi.getList(params),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => strategiesApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['strategies'] });
    },
  });

  const handleDelete = (id: string) => {
    if (confirm('确定要删除此策略吗？')) {
      deleteMutation.mutate(id);
    }
  };

  const strategies = data?.data?.items || [];
  const total = data?.data?.total || 0;
  const totalPages = Math.ceil(total / pageSize);

  return (
    <RequireAuth>
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold">策略管理</h1>
            <p className="text-muted-foreground">创建、管理和监控您的量化策略</p>
          </div>
          <Button disabled title="Phase 4 开放策略创建">
            创建策略（Phase 4）
          </Button>
        </div>

        <Card className="border-brand/30 bg-brand-soft">
          <CardContent className="p-4 text-sm text-muted-foreground">
            策略管理属于 Phase 4 量化研究范围。当前仅保留占位入口，避免误以为已经支持真实创建、
            编辑、运行和删除策略。
          </CardContent>
        </Card>

        {/* 筛选和搜索 */}
        <Card>
          <CardHeader>
            <CardTitle>筛选条件</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex gap-4">
              <Input
                placeholder="搜索策略名称..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="max-w-xs"
              />
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as Strategy['status'] | 'all')}
                className="px-3 py-2 border rounded-md"
              >
                <option value="all">全部状态</option>
                <option value="draft">草稿</option>
                <option value="active">运行中</option>
                <option value="paused">已暂停</option>
                <option value="stopped">已停止</option>
              </select>
              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value as Strategy['type'] | 'all')}
                className="px-3 py-2 border rounded-md"
              >
                <option value="all">全部类型</option>
                <option value="trend_following">趋势跟踪</option>
                <option value="mean_reversion">均值回归</option>
                <option value="arbitrage">套利</option>
                <option value="momentum">动量</option>
                <option value="other">其他</option>
              </select>
            </div>
          </CardContent>
        </Card>

        {/* 策略列表 */}
        <Card>
          <CardHeader>
            <CardTitle>策略列表</CardTitle>
            <CardDescription>共 {total} 个策略</CardDescription>
          </CardHeader>
          <CardContent>
            {isLoading ? (
              <div className="text-center py-8">加载中...</div>
            ) : strategies.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                策略功能暂未开放，Phase 4 将提供真实策略 CRUD 与回测集成。
              </div>
            ) : (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>策略名称</TableHead>
                      <TableHead>类型</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>累计收益</TableHead>
                      <TableHead>更新时间</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {strategies.map((strategy) => (
                      <TableRow key={strategy.id}>
                        <TableCell className="font-medium">
                          <Link
                            href={`/strategies/${strategy.id}`}
                            className="hover:underline"
                          >
                            {strategy.name}
                          </Link>
                        </TableCell>
                        <TableCell>{STRATEGY_TYPE_MAP[strategy.type]}</TableCell>
                        <TableCell>
                          <span
                            className={`px-2 py-1 rounded text-xs ${
                              STRATEGY_STATUS_MAP[strategy.status].className
                            }`}
                          >
                            {STRATEGY_STATUS_MAP[strategy.status].label}
                          </span>
                        </TableCell>
                        <TableCell>
                          {strategy.performance ? (
                            <span
                              className={
                                strategy.performance.totalReturnPercent >= 0
                                  ? 'text-up'
                                  : 'text-down'
                              }
                            >
                              {formatPercent(strategy.performance.totalReturnPercent)}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                        </TableCell>
                        <TableCell className="text-sm text-muted-foreground">
                          {formatDate(strategy.updatedAt)}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex justify-end gap-2">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => router.push(`/strategies/${strategy.id}/edit`)}
                            >
                              编辑
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              onClick={() => handleDelete(strategy.id)}
                            >
                              删除
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                {/* 分页 */}
                {totalPages > 1 && (
                  <div className="flex justify-center gap-2 mt-4">
                    <Button
                      variant="outline"
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                      disabled={page === 1}
                    >
                      上一页
                    </Button>
                    <span className="flex items-center px-4">
                      第 {page} / {totalPages} 页
                    </span>
                    <Button
                      variant="outline"
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      disabled={page === totalPages}
                    >
                      下一页
                    </Button>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </RequireAuth>
  );
}


