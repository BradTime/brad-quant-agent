import type { BacktestConfig, BacktestResult } from '@/types/backtest';
import { apiClient } from './client';

/**
 * 回测分析相关 API
 */
export const backtestApi = {
  /**
   * 执行回测
   */
  run: async (config: BacktestConfig): Promise<BacktestResult> => {
    const response = await apiClient.post<BacktestResult>('/backtest/run', config);
    return response.data;
  },

  /**
   * 获取回测结果
   */
  getResult: async (id: string): Promise<BacktestResult> => {
    const response = await apiClient.get<BacktestResult>(`/backtest/${id}`);
    return response.data;
  },

  /**
   * 获取回测指标
   */
  getMetrics: async (id: string) => {
    const response = await apiClient.get(`/backtest/${id}/metrics`);
    return response.data;
  },

  /**
   * 获取回测报告
   */
  getReport: async (id: string) => {
    const response = await apiClient.get(`/backtest/${id}/report`);
    return response.data;
  },

  /**
   * 导出回测报告
   */
  exportReport: async (id: string, format: 'pdf' | 'excel' = 'pdf') => {
    const response = await apiClient.post(`/backtest/${id}/export`, { format }, {
      responseType: 'blob',
    });
    return response.data;
  },
};


