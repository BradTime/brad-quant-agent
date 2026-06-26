import type { ApiResponse } from '@/types';
import type { BacktestMetrics, EquityPoint, TradeRecord } from '@/types/backtest';
import { apiClient } from './client';

/** 内置策略目录项（后端 /backtest/strategies 返回，驱动前端参数表单）。 */
export interface StrategyParamSpec {
  key: string;
  label: string;
  type: 'int' | 'float';
  default: number;
  min?: number;
  max?: number;
}

export interface StrategyCatalogItem {
  type: string;
  name: string;
  description: string;
  params: StrategyParamSpec[];
}

export interface BacktestRunRequest {
  strategyType: string;
  params: Record<string, number>;
  codes: string[];
  start: string;
  end: string;
  initialCapital: number;
  slippage: number;
  engine?: string;
}

export interface BacktestRunResult {
  id: string;
  strategyType: string;
  status: 'completed' | 'failed';
  engine: string;
  error?: string | null;
  createdAt: string;
  config: Record<string, unknown>;
  metrics: Partial<BacktestMetrics>;
  equityCurve?: EquityPoint[];
  trades?: TradeRecord[];
  dataQuality?: Record<string, string>;
}

// apiClient 的响应拦截器返回整个信封 { code, message, data }，业务数据在 .data
async function unwrap<T>(p: Promise<unknown>): Promise<T> {
  const env = (await p) as ApiResponse<T>;
  return env.data as T;
}

export const backtestApi = {
  strategyCatalog: () =>
    unwrap<{ items: StrategyCatalogItem[] }>(apiClient.get('/backtest/strategies')),
  run: (req: BacktestRunRequest) =>
    unwrap<BacktestRunResult>(apiClient.post('/backtest/run', req)),
  list: () =>
    unwrap<{ items: BacktestRunResult[]; total: number }>(apiClient.get('/backtest')),
  get: (id: string) => unwrap<BacktestRunResult>(apiClient.get(`/backtest/${id}`)),
};
