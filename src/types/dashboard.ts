/**
 * 仪表盘相关类型定义
 */

export interface DashboardStats {
  totalAssets: number;
  todayReturn: number;
  todayReturnPercent: number;
  cumulativeReturn: number;
  cumulativeReturnPercent: number;
  runningStrategies: number;
  totalStrategies: number;
}

export interface MarketOverview {
  index: string;
  name: string;
  value: number;
  change: number;
  changePercent: number;
}

export interface RecentTrade {
  id: string;
  symbol: string;
  name: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  timestamp: string;
}

export interface PositionDistribution {
  symbol: string;
  name: string;
  value: number;
  percent: number;
  cost: number;
  currentPrice: number;
  return: number;
  returnPercent: number;
}

export interface ReturnData {
  date: string;
  value: number;
  benchmark?: number;
}


