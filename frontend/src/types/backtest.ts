/**
 * 回测分析相关类型定义
 */

export interface BacktestConfig {
  strategyId: string;
  startDate: string;
  endDate: string;
  initialCapital: number;
  commission: number;
  slippage: number;
  dataSource?: string;
}

export interface BacktestResult {
  id: string;
  strategyId: string;
  config: BacktestConfig;
  status: 'pending' | 'running' | 'completed' | 'failed';
  createdAt: string;
  completedAt?: string;
  metrics?: BacktestMetrics;
  equityCurve?: EquityPoint[];
  trades?: TradeRecord[];
}

export interface BacktestMetrics {
  totalReturn: number;
  totalReturnPercent: number;
  annualReturn: number;
  annualReturnPercent: number;
  sharpeRatio: number;
  sortinoRatio: number;
  maxDrawdown: number;
  maxDrawdownPercent: number;
  winRate: number;
  profitFactor: number;
  averageWin: number;
  averageLoss: number;
  totalTrades: number;
  winningTrades: number;
  losingTrades: number;
}

export interface EquityPoint {
  date: string;
  equity: number;
  return: number;
  returnPercent: number;
}

export interface TradeRecord {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  entryPrice: number;
  exitPrice: number;
  entryTime: string;
  exitTime: string;
  return: number;
  returnPercent: number;
  commission: number;
}


