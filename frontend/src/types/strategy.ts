/**
 * 策略管理相关类型定义
 */

export type BuiltinStrategyType =
  | 'dual_ma'
  | 'rsi'
  | 'boll'
  | 'momentum'
  | 'donchian_breakout'
  | 'xs_momentum'
  | 'zscore_reversion'
  | 'composite_mf'
  | 'flow_surge'
  | 'fundamental_quality';
export type StrategyImplementationType = BuiltinStrategyType | 'custom_python';
export type StrategyDefinitionType = 'builtin' | 'custom_python';
export type StrategyCategory =
  | 'trend_following'
  | 'mean_reversion'
  | 'momentum'
  | 'multi_factor'
  | 'event'
  | 'custom';
export type StrategyStatus = 'draft' | 'active' | 'disabled';

export interface Strategy {
  id: string;
  name: string;
  description: string;
  category: StrategyCategory;
  builtinType: StrategyImplementationType;
  definitionType: StrategyDefinitionType;
  currentVersion: number;
  protocolVersion: string;
  implementationVersion: string;
  definitionSha256: string;
  sourceCode?: string;
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
  builtinType?: StrategyImplementationType;
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
  expectedVersion?: number;
}
