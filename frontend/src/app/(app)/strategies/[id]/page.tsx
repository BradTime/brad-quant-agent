'use client';

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter, useParams } from 'next/navigation';
import Link from 'next/link';
import { RequireAuth } from '@/components/auth/require-auth';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { strategiesApi } from '@/lib/api/strategies';
import { formatPercent, formatDate } from '@/lib/utils/format';

const STRATEGY_TYPE_MAP: Record<string, string> = {
  trend_following: '趋势跟踪',
  mean_reversion: '均值回归',
  arbitrage: '套利',
  momentum: '动量',
  other: '其他',
};

const STRATEGY_STATUS_MAP: Record<string, { label: string; className: string }> = {
  draft: { label: '草稿', className: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200' },
  active: { label: '运行中', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
  paused: { label: '已暂停', className: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' },
  stopped: { label: '已停止', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
};

export default function StrategyDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const strategyId = params?.id ?? '';
  const queryClient = useQueryClient();

  const { data: strategy, isLoading } = useQuery({
    queryKey: ['strategy', strategyId],
    queryFn: () => strategiesApi.getDetail(strategyId),
    enabled: !!strategyId,
  });

  const enableMutation = useMutation({
    mutationFn: () => strategiesApi.enable(strategyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['strategy', strategyId] });
      queryClient.invalidateQueries({ queryKey: ['strategies'] });
    },
  });

  const disableMutation = useMutation({
    mutationFn: () => strategiesApi.disable(strategyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['strategy', strategyId] });
      queryClient.invalidateQueries({ queryKey: ['strategies'] });
    },
  });

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

  const performance = strategy.performance;

  return (
    <RequireAuth>
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex justify-between items-start">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <h1 className="text-3xl font-bold">{strategy.name}</h1>
              <span
                className={`px-3 py-1 rounded text-sm ${
                  STRATEGY_STATUS_MAP[strategy.status]?.className || ''
                }`}
              >
                {STRATEGY_STATUS_MAP[strategy.status]?.label || strategy.status}
              </span>
            </div>
            <p className="text-muted-foreground">{strategy.description || '暂无描述'}</p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => router.push(`/strategies/${strategy.id}/edit`)}
            >
              编辑
            </Button>
            {strategy.status === 'active' ? (
              <Button
                variant="outline"
                onClick={() => disableMutation.mutate()}
                disabled={disableMutation.isPending}
              >
                停用
              </Button>
            ) : (
              <Button
                onClick={() => enableMutation.mutate()}
                disabled={enableMutation.isPending}
              >
                启用
              </Button>
            )}
          </div>
        </div>

        {/* 基本信息 */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">策略类型</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-lg">{STRATEGY_TYPE_MAP[strategy.type] || strategy.type}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">创建时间</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm">{formatDate(strategy.createdAt)}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">更新时间</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm">{formatDate(strategy.updatedAt)}</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-medium">策略ID</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm font-mono">{strategy.id}</div>
            </CardContent>
          </Card>
        </div>

        {/* 性能指标 */}
        {performance && (
          <Card>
            <CardHeader>
              <CardTitle>性能指标</CardTitle>
              <CardDescription>策略运行以来的关键指标</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                <div>
                  <div className="text-sm text-muted-foreground mb-1">累计收益</div>
                  <div
                    className={`text-2xl font-bold ${
                      performance.totalReturnPercent >= 0 ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {formatPercent(performance.totalReturnPercent)}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">年化收益</div>
                  <div className="text-2xl font-bold">{formatPercent(performance.annualReturn)}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">夏普比率</div>
                  <div className="text-2xl font-bold">{performance.sharpeRatio.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">最大回撤</div>
                  <div className="text-2xl font-bold text-red-600">
                    {formatPercent(-Math.abs(performance.maxDrawdown))}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">胜率</div>
                  <div className="text-2xl font-bold">{formatPercent(performance.winRate * 100)}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">总交易次数</div>
                  <div className="text-2xl font-bold">{performance.totalTrades}</div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* 策略参数 */}
        <Card>
          <CardHeader>
            <CardTitle>策略参数</CardTitle>
          </CardHeader>
          <CardContent>
            <pre className="bg-muted p-4 rounded-md overflow-auto">
              {JSON.stringify(strategy.params, null, 2)}
            </pre>
          </CardContent>
        </Card>

        {/* 策略代码 */}
        {strategy.code && (
          <Card>
            <CardHeader>
              <CardTitle>策略代码</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="bg-muted p-4 rounded-md overflow-auto text-sm font-mono">
                {strategy.code}
              </pre>
            </CardContent>
          </Card>
        )}
      </div>
    </RequireAuth>
  );
}

