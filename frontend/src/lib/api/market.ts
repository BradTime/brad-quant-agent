import { apiClient } from './client';

export interface StockQuote {
  code: string;
  name: string;
  price: number;
  change: number;
  changePercent: number;
  volume: number;
  amount: number;
  high?: number;
  low?: number;
  open?: number;
  yesterdayClose?: number;
  timestamp: number;
}

export interface KlineData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface QuotesResponse {
  stocks: StockQuote[];
  total: number;
  page: number;
  pageSize: number;
}

/**
 * 市场行情相关 API
 */
export const marketApi = {
  /**
   * 获取市场行情（所有股票，支持分页和排序）
   */
  getQuotes: async (
    page = 1,
    pageSize = 20,
    sortBy: 'price' | 'changePercent' | 'volume' = 'price',
    sortOrder: 'asc' | 'desc' = 'desc'
  ): Promise<QuotesResponse> => {
    const response = await apiClient.get<QuotesResponse>('/market/quotes', {
      params: { page, pageSize, sortBy, sortOrder },
    });
    return response.data;
  },

  /**
   * 获取热门股票（最多20只，向后兼容）
   */
  getPopularQuotes: async (limit = 20): Promise<StockQuote[]> => {
    const response = await apiClient.get<StockQuote[]>('/market/quotes/popular', {
      params: { limit },
    });
    return response.data;
  },

  /**
   * 获取指数数据
   */
  getIndexes: async (): Promise<StockQuote[]> => {
    const response = await apiClient.get<StockQuote[]>('/market/indexes');
    return response.data;
  },

  /**
   * 获取K线数据
   */
  getKline: async (
    symbol: string,
    period: '1min' | '5min' | '15min' | '30min' | 'hour' | 'day' = 'day',
    count = 100
  ): Promise<KlineData[]> => {
    const response = await apiClient.get<KlineData[]>('/market/kline', {
      params: { symbol, period, count },
    });
    return response.data;
  },
};

