/**
 * 策略管理相关类型定义
 */

export type BuiltinStrategyType = 'dual_ma' | 'rsi' | 'boll' | 'momentum';
export type StrategyCategory = 'trend_following' | 'mean_reversion' | 'momentum';
export type StrategyStatus = 'draft' | 'active' | 'disabled';

export interface Strategy {
  id: string;
  name: string;
  description: string;
  category: StrategyCategory;
  builtinType: BuiltinStrategyType;
  status: StrategyStatus;
  createdAt: string;
  updatedAt: string;
  userId: string;
  params: Record<string, number>;
}

export interface StrategyListParams {
  page?: number;
  pageSize?: number;
  status?: StrategyStatus;
  category?: StrategyCategory;
  builtinType?: BuiltinStrategyType;
  sortBy?: 'name' | 'createdAt' | 'updatedAt' | 'status';
  sortOrder?: 'asc' | 'desc';
  search?: string;
}

export interface StrategyCreateRequest {
  name: string;
  description: string;
  builtinType: BuiltinStrategyType;
  params: Record<string, number>;
}

export interface StrategyUpdateRequest extends Partial<StrategyCreateRequest> {
  id: string;
}
