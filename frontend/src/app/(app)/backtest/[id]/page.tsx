'use client';

import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { RequireAuth } from '@/components/auth/require-auth';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LineChart } from '@/components/charts';
import { backtestApi } from '@/lib/api/backtest';
import { formatPercent, formatCurrency, formatDate } from '@/lib/utils/format';

const STATUS_MAP: Record<string, { label: string; className: string }> = {
  pending: { label: '等待中', className: 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200' },
  running: { label: '运行中', className: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200' },
  completed: { label: '已完成', className: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' },
  failed: { label: '失败', className: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' },
};

export default function BacktestResultPage() {
  const params = useParams();
  const backtestId = params.id as string;

  const { data: result, isLoading } = useQuery({
    queryKey: ['backtest', backtestId],
    queryFn: () => backtestApi.getResult(backtestId),
    enabled: !!backtestId,
    refetchInterval: (data) => {
      // 如果回测还在运行中，每5秒刷新一次
      return data?.status === 'running' ? 5000 : false;
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

  if (!result) {
    return (
      <RequireAuth>
        <div className="container mx-auto p-6">
          <div className="text-center py-8">
            <p className="text-muted-foreground">回测结果不存在</p>
            <Link href="/backtest/new">
              <Button className="mt-4">新建回测</Button>
            </Link>
          </div>
        </div>
      </RequireAuth>
    );
  }

  const metrics = result.metrics;
  const equityCurve = result.equityCurve || [];

  return (
    <RequireAuth>
      <div className="container mx-auto p-6 space-y-6">
        <div className="flex justify-between items-start">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <h1 className="text-3xl font-bold">回测结果</h1>
              <span className={`px-3 py-1 rounded text-sm ${STATUS_MAP[result.status]?.className || ''}`}>
                {STATUS_MAP[result.status]?.label || result.status}
              </span>
            </div>
            <p className="text-muted-foreground">
              回测时间：{formatDate(result.createdAt, 'long')}
              {result.completedAt && ` - ${formatDate(result.completedAt, 'long')}`}
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline">导出报告</Button>
            <Link href="/backtest/new">
              <Button>新建回测</Button>
            </Link>
          </div>
        </div>

        {/* 关键指标 */}
        {metrics && (
          <Card>
            <CardHeader>
              <CardTitle>关键指标</CardTitle>
              <CardDescription>回测的关键性能指标</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                <div>
                  <div className="text-sm text-muted-foreground mb-1">总收益</div>
                  <div
                    className={`text-2xl font-bold ${
                      metrics.totalReturnPercent >= 0 ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {formatPercent(metrics.totalReturnPercent)}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">年化收益</div>
                  <div className="text-2xl font-bold">{formatPercent(metrics.annualReturnPercent)}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">夏普比率</div>
                  <div className="text-2xl font-bold">{metrics.sharpeRatio.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">最大回撤</div>
                  <div className="text-2xl font-bold text-red-600">
                    {formatPercent(-Math.abs(metrics.maxDrawdownPercent))}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">胜率</div>
                  <div className="text-2xl font-bold">{formatPercent(metrics.winRate * 100)}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">盈利因子</div>
                  <div className="text-2xl font-bold">{metrics.profitFactor.toFixed(2)}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">总交易次数</div>
                  <div className="text-2xl font-bold">{metrics.totalTrades}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">平均盈亏比</div>
                  <div className="text-2xl font-bold">
                    {metrics.averageWin !== 0 && metrics.averageLoss !== 0
                      ? (Math.abs(metrics.averageWin / metrics.averageLoss)).toFixed(2)
                      : '-'}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* 收益曲线 */}
        {equityCurve.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>资产曲线</CardTitle>
              <CardDescription>回测期间的资产变化曲线</CardDescription>
            </CardHeader>
            <CardContent>
              <LineChart
                data={equityCurve.map((point) => ({
                  date: point.date,
                  value: point.returnPercent,
                }))}
                height={400}
                title="资产曲线"
              />
            </CardContent>
          </Card>
        )}

        {/* 回测配置 */}
        <Card>
          <CardHeader>
            <CardTitle>回测配置</CardTitle>
          </CardHeader>
            <CardContent>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <div className="text-sm text-muted-foreground mb-1">策略ID</div>
                  <div className="font-mono">{result.config.strategyId}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">回测期间</div>
                  <div>
                    {formatDate(result.config.startDate)} - {formatDate(result.config.endDate)}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">初始资金</div>
                  <div>{formatCurrency(result.config.initialCapital)}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">手续费率</div>
                  <div>{formatPercent(result.config.commission * 100)}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground mb-1">滑点</div>
                  <div>{formatPercent(result.config.slippage * 100)}</div>
                </div>
              </div>
            </CardContent>
        </Card>
      </div>
    </RequireAuth>
  );
}


