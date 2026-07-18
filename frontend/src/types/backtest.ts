/**
 * 回测分析相关类型定义
 */
export type BacktestFrequency = '1d' | '5m' | '15m' | '30m' | '60m';
export type BacktestEngine = 'native' | 'backtrader';
export type BacktestStrategyType = 'dual_ma' | 'rsi' | 'boll' | 'momentum';
export type GridSortMetric =
  | 'totalReturnPercent'
  | 'annualReturnPercent'
  | 'sharpeRatio'
  | 'maxDrawdownPercent'
  | 'winRate'
  | 'totalTrades'
  | 'excessReturnPercent';

export interface BacktestConfig {
  strategyType: BacktestStrategyType;
  params: Record<string, number>;
  codes: string[];
  start: string;
  end: string;
  initialCapital: number;
  slippage: number;
  engine: BacktestEngine;
  frequency: BacktestFrequency;
}

export interface BacktestResult {
  id: string;
  strategyType: BacktestStrategyType;
  config: BacktestConfig;
  status: 'completed' | 'failed';
  engine: BacktestEngine;
  error?: string | null;
  createdAt: string;
  metrics: Partial<BacktestMetrics>;
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

export type BacktestJobStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface BacktestJob {
  id: string;
  userId: string;
  kind: string;
  status: BacktestJobStatus;
  cancelRequested: boolean;
  progressDone: number;
  progressTotal: number;
  error?: string | null;
  request?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
}

