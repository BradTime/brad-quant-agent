import type { DashboardStats, MarketOverview, RecentTrade, PositionDistribution } from '@/types/dashboard';
import { apiClient } from './client';

/**
 * 仪表盘相关 API
 */
export const dashboardApi = {
  /**
   * 获取仪表盘统计数据
   */
  getStats: async (): Promise<DashboardStats> => {
    const response = await apiClient.get<DashboardStats>('/dashboard/stats');
    return response.data;
  },

  /**
   * 获取市场概览
   */
  getMarketOverview: async (): Promise<MarketOverview[]> => {
    const response = await apiClient.get<MarketOverview[]>('/dashboard/market-overview');
    return response.data;
  },

  /**
   * 获取最近交易记录
   */
  getRecentTrades: async (limit = 10): Promise<RecentTrade[]> => {
    const response = await apiClient.get<RecentTrade[]>('/dashboard/recent-trades', {
      params: { limit },
    });
    return response.data;
  },

  /**
   * 获取持仓分布
   */
  getPositionDistribution: async (): Promise<PositionDistribution[]> => {
    const response = await apiClient.get<PositionDistribution[]>('/dashboard/position-distribution');
    return response.data;
  },

  /**
   * 获取收益曲线数据
   */
  getReturnCurve: async (days = 30): Promise<Array<{ date: string; value: number; benchmark?: number }>> => {
    const response = await apiClient.get<Array<{ date: string; value: number; benchmark?: number }>>(
      '/dashboard/return-curve',
      {
        params: { days },
      }
    );
    return response.data;
  },
};


