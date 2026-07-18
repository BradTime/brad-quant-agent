'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { RequireAuth } from '@/components/auth/require-auth';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LineChart, PieChart } from '@/components/charts';
import { dashboardApi } from '@/lib/api/dashboard';
import { marketApi } from '@/lib/api/market';
import { ageQuote, formatQuoteFreshness } from '@/lib/api/quote-selection';
import { useFreshnessClock } from '@/hooks/useFreshnessClock';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  formatAmount,
  formatCurrency,
  formatPercent,
  formatVolume,
} from '@/lib/utils/format';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Button } from '@/components/ui/button';
import { ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react';

function changeClass(value: number | null): string {
  if (value === null || value === 0) return 'text-muted-foreground';
  return value > 0 ? 'text-up' : 'text-down';
}

function fixed(value: number | null): string {
  return value === null ? '—' : value.toFixed(2);
}

function signed(value: number | null, suffix = ''): string {
  return value === null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(2)}${suffix}`;
}

export default function DashboardPage() {
  // 分页和排序状态
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [sortBy, setSortBy] = useState<'price' | 'changePercent' | 'volume'>('price');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const freshnessNow = useFreshnessClock();
  const userId = useAuthStore((state) => state.user?.id);

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['dashboard', userId ?? 'anonymous', 'stats'],
    queryFn: () => dashboardApi.getStats(),
    enabled: Boolean(userId),
    refetchInterval: 30000, // 30秒刷新一次
  });

  const { data: marketOverview = [], dataUpdatedAt: overviewReceivedAt } = useQuery({
    queryKey: ['dashboard', 'market-overview'],
    queryFn: () => dashboardApi.getMarketOverview(),
    refetchInterval: 10000, // 10秒刷新一次；本地时钟负责失败后的继续老化
  });

  const {
    data: quotesData,
    dataUpdatedAt: quotesReceivedAt,
    isLoading: quotesLoading,
    refetch: refetchQuotes,
  } = useQuery({
    queryKey: ['market', 'quotes', page, pageSize, sortBy, sortOrder],
    queryFn: () => marketApi.getQuotes(page, pageSize, sortBy, sortOrder),
    refetchInterval: 5000, // 5秒刷新一次；失败时保留数据并由本地时钟标记过期
  });

  const agedOverview = marketOverview.map((index) =>
    ageQuote(index, overviewReceivedAt, freshnessNow)
  );
  const stockQuotes = (quotesData?.stocks || []).map((quote) =>
    ageQuote(quote, quotesReceivedAt, freshnessNow)
  );
  const overviewFreshness = agedOverview[0]
    ? formatQuoteFreshness(agedOverview[0])
    : null;
  const stockFreshness = stockQuotes[0]
    ? formatQuoteFreshness(stockQuotes[0])
    : null;
  const total = quotesData?.total || 0;
  const totalPages = Math.ceil(total / pageSize);

  // 处理排序点击
  const handleSort = (field: 'price' | 'changePercent' | 'volume') => {
    if (sortBy === field) {
      // 如果是同一字段，切换排序顺序
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      // 如果是新字段，设置默认降序
      setSortBy(field);
      setSortOrder('desc');
    }
    // 重置到第一页
    setPage(1);
  };

  // 获取排序图标
  const getSortIcon = (field: 'price' | 'changePercent' | 'volume') => {
    if (sortBy !== field) {
      return <ArrowUpDown className="ml-1 h-3 w-3 opacity-50" />;
    }
    return sortOrder === 'asc' ? (
      <ArrowUp className="ml-1 h-3 w-3" />
    ) : (
      <ArrowDown className="ml-1 h-3 w-3" />
    );
  };

  const { data: returnCurve, isLoading: curveLoading } = useQuery({
    queryKey: ['dashboard', userId ?? 'anonymous', 'return-curve'],
    queryFn: () => dashboardApi.getReturnCurve(30),
    enabled: Boolean(userId),
  });

  const { data: positionDist, isLoading: distLoading } = useQuery({
    queryKey: ['dashboard', userId ?? 'anonymous', 'position-distribution'],
    queryFn: () => dashboardApi.getPositionDistribution(),
    enabled: Boolean(userId),
  });

  const { data: recentTrades, isLoading: tradesLoading } = useQuery({
    queryKey: ['dashboard', userId ?? 'anonymous', 'recent-trades'],
    queryFn: () => dashboardApi.getRecentTrades(5),
    enabled: Boolean(userId),
  });

  return (
    <RequireAuth>
      <div className="container mx-auto p-6 space-y-6">
        <div>
          <h1 className="text-3xl font-bold">仪表盘</h1>
          <p className="text-muted-foreground">欢迎来到量化投资 Agent 平台</p>
        </div>

        {/* 市场指数概览 */}
        {agedOverview.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>A股指数</CardTitle>
              <CardDescription>
                {overviewFreshness?.text ?? '不可用'}（数据来源：东方财富）
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-4 md:grid-cols-3">
                {agedOverview.map((index) => {
                  const freshness = formatQuoteFreshness(index);
                  return (
                    <div key={index.index} className="border rounded-lg p-4">
                      <div className="text-sm text-muted-foreground mb-1">{index.name}</div>
                      <div className="text-2xl font-bold mb-1">
                        {fixed(index.value)}
                      </div>
                      <div className={`text-sm font-semibold ${changeClass(index.change)}`}>
                        {signed(index.change)} ({signed(index.changePercent, '%')})
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {freshness.text}
                      </div>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        )}

        {/* A股行情表格 */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>A股行情</CardTitle>
              <CardDescription>
                {stockFreshness?.text ?? '不可用'} · 共 {total} 只股票（每5秒自动刷新，每页 {pageSize} 只）
              </CardDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => refetchQuotes()}
              disabled={quotesLoading}
            >
              {quotesLoading ? '刷新中...' : '刷新'}
            </Button>
          </CardHeader>
          <CardContent>
            {quotesLoading ? (
              <div className="text-center py-8">加载中...</div>
            ) : stockQuotes && stockQuotes.length > 0 ? (
              <>
                <div className="overflow-x-auto">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>代码</TableHead>
                        <TableHead>名称</TableHead>
                        <TableHead className="text-right">
                          <button
                            onClick={() => handleSort('price')}
                            className="flex items-center justify-end gap-1 hover:text-foreground transition-colors"
                          >
                            现价
                            {getSortIcon('price')}
                          </button>
                        </TableHead>
                        <TableHead className="text-right">涨跌</TableHead>
                        <TableHead className="text-right">
                          <button
                            onClick={() => handleSort('changePercent')}
                            className="flex items-center justify-end gap-1 hover:text-foreground transition-colors"
                          >
                            涨跌幅
                            {getSortIcon('changePercent')}
                          </button>
                        </TableHead>
                        <TableHead className="text-right">
                          <button
                            onClick={() => handleSort('volume')}
                            className="flex items-center justify-end gap-1 hover:text-foreground transition-colors"
                          >
                            成交量
                            {getSortIcon('volume')}
                          </button>
                        </TableHead>
                        <TableHead className="text-right">成交额</TableHead>
                        <TableHead className="text-right">状态</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {stockQuotes.map((stock) => (
                        <TableRow key={stock.code}>
                          <TableCell className="font-mono">{stock.code}</TableCell>
                          <TableCell className="font-medium">{stock.name}</TableCell>
                          <TableCell className="text-right font-semibold tnum">
                            {fixed(stock.price)}
                          </TableCell>
                          <TableCell
                            className={`text-right ${changeClass(stock.change)}`}
                          >
                            {signed(stock.change)}
                          </TableCell>
                          <TableCell
                            className={`text-right font-semibold ${changeClass(stock.changePercent)}`}
                          >
                            {signed(stock.changePercent, '%')}
                          </TableCell>
                          <TableCell className="text-right text-sm text-muted-foreground">
                            {formatVolume(stock.volume, '手')}
                          </TableCell>
                          <TableCell className="text-right text-sm text-muted-foreground">
                            {formatAmount(stock.amount)}
                          </TableCell>
                          <TableCell className="text-right text-xs text-muted-foreground">
                            {formatQuoteFreshness(stock).text}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>

                {/* 分页控件 */}
                {totalPages > 1 && (
                  <div className="flex items-center justify-between mt-4">
                    <div className="text-sm text-muted-foreground">
                      显示第 {(page - 1) * pageSize + 1} - {Math.min(page * pageSize, total)} 条，共 {total} 条
                    </div>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPage((p) => Math.max(1, p - 1))}
                        disabled={page === 1 || quotesLoading}
                      >
                        上一页
                      </Button>
                      <div className="flex items-center px-4">
                        <span className="text-sm">
                          第 {page} / {totalPages} 页
                        </span>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                        disabled={page === totalPages || quotesLoading}
                      >
                        下一页
                      </Button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="text-center py-8 text-muted-foreground">暂无行情数据</div>
            )}
          </CardContent>
        </Card>

        {/* 统计卡片 */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader>
              <CardTitle>总资产</CardTitle>
              <CardDescription>当前总资产</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? '加载中...' : formatCurrency(stats?.totalAssets ?? 0)}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>今日收益</CardTitle>
              <CardDescription>今日盈亏</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? '加载中...' : (
                  <span className={(stats?.todayReturn ?? 0) >= 0 ? 'text-up' : 'text-down'}>
                    {formatCurrency(stats?.todayReturn ?? 0)} ({formatPercent(stats?.todayReturnPercent ?? 0)})
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>累计收益</CardTitle>
              <CardDescription>总盈亏</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? '加载中...' : (
                  <span className={(stats?.cumulativeReturn ?? 0) >= 0 ? 'text-up' : 'text-down'}>
                    {formatCurrency(stats?.cumulativeReturn ?? 0)} ({formatPercent(stats?.cumulativeReturnPercent ?? 0)})
                  </span>
                )}
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>运行策略</CardTitle>
              <CardDescription>当前运行的策略数量</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">
                {statsLoading ? '加载中...' : `${stats?.runningStrategies ?? 0} / ${stats?.totalStrategies ?? 0}`}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* 图表区域 */}
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>收益曲线</CardTitle>
              <CardDescription>过去 30 天收益走势</CardDescription>
            </CardHeader>
            <CardContent>
              {curveLoading ? (
                <div className="flex items-center justify-center h-[300px]">加载中...</div>
              ) : returnCurve && returnCurve.length > 0 ? (
                <LineChart data={returnCurve} height={300} />
              ) : (
                <div className="flex items-center justify-center h-[300px] text-muted-foreground">
                  暂无模拟交易数据
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>持仓分布</CardTitle>
              <CardDescription>当前持仓占比</CardDescription>
            </CardHeader>
            <CardContent>
              {distLoading ? (
                <div className="flex items-center justify-center h-[300px]">加载中...</div>
              ) : positionDist && positionDist.length > 0 ? (
                <PieChart
                  data={positionDist.map((p) => ({
                    name: p.name,
                    value: p.value,
                  }))}
                  height={300}
                />
              ) : (
                <div className="flex items-center justify-center h-[300px] text-muted-foreground">
                  暂无模拟交易数据
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* 最近交易记录 */}
        <Card>
          <CardHeader>
            <CardTitle>最近交易</CardTitle>
            <CardDescription>最近的交易记录</CardDescription>
          </CardHeader>
          <CardContent>
            {tradesLoading ? (
              <div className="text-center py-4">加载中...</div>
            ) : recentTrades && recentTrades.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left p-2">时间</th>
                      <th className="text-left p-2">标的</th>
                      <th className="text-left p-2">方向</th>
                      <th className="text-right p-2">数量</th>
                      <th className="text-right p-2">价格</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentTrades.map((trade) => (
                      <tr key={trade.id} className="border-b">
                        <td className="p-2 text-sm text-muted-foreground">
                          {new Date(trade.timestamp).toLocaleString('zh-CN')}
                        </td>
                        <td className="p-2">{trade.name}</td>
                        <td className="p-2">
                          <span className={trade.side === 'buy' ? 'text-green-600' : 'text-red-600'}>
                            {trade.side === 'buy' ? '买入' : '卖出'}
                          </span>
                        </td>
                        <td className="p-2 text-right">{trade.quantity}</td>
                        <td className="p-2 text-right">{formatCurrency(trade.price)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-4 text-muted-foreground">
                暂无模拟交易数据
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </RequireAuth>
  );
}

