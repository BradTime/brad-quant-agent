/**
 * 策略管理相关类型定义
 */

export interface Strategy {
  id: string;
  name: string;
  description?: string;
  type: 'trend_following' | 'mean_reversion' | 'arbitrage' | 'momentum' | 'other';
  status: 'draft' | 'active' | 'paused' | 'stopped';
  createdAt: string;
  updatedAt: string;
  userId: string;
  params: Record<string, unknown>;
  code?: string;
  performance?: StrategyPerformance;
}

export interface StrategyPerformance {
  totalReturn: number;
  totalReturnPercent: number;
  annualReturn: number;
  sharpeRatio: number;
  maxDrawdown: number;
  winRate: number;
  totalTrades: number;
}

export interface StrategyListParams {
  page?: number;
  pageSize?: number;
  status?: Strategy['status'];
  type?: Strategy['type'];
  sortBy?: 'createdAt' | 'updatedAt' | 'totalReturn';
  sortOrder?: 'asc' | 'desc';
  search?: string;
}

export interface StrategyCreateRequest {
  name: string;
  description?: string;
  type: Strategy['type'];
  params: Record<string, unknown>;
  code?: string;
}

export interface StrategyUpdateRequest extends Partial<StrategyCreateRequest> {
  id: string;
}


