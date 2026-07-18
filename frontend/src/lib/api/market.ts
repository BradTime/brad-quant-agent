import { apiClient } from './client';

export type QuoteStaleReason =
  | 'last_close'
  | 'missing_as_of'
  | 'missing_cache_refresh'
  | 'quote_expired'
  | 'cache_expired'
  | 'unverified_event_time'
  | 'market_closed'
  | 'invalid_price';

export interface StockQuote {
  code: string;
  name: string;
  price: number | null;
  change: number | null;
  changePercent: number | null;
  volume: number | null;
  amount: number | null;
  high?: number | null;
  low?: number | null;
  open?: number | null;
  yesterdayClose?: number | null;
  /** 兼容字段，与 asOf 同源；不是 API/WS 的发送时间。 */
  timestamp: number;
  /** 行情数据本身的观测时间（Unix ms），未知时为 null。 */
  asOf: number | null;
  /** data asOf 与缓存刷新时间中较老者的年龄（ms）。 */
  ageMs: number | null;
  /** 服务端用于判定可成交的最大快照年龄（ms）。 */
  maxAgeMs: number;
  stale: boolean;
  /** 陈旧或不可成交原因；market_closed 可在 stale=false 时出现。 */
  staleReason: QuoteStaleReason | null;
  /** 仅价格正数、快照未超龄且处于 A 股交易时段时为 true。 */
  executable: boolean;
}

export interface KlineData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
}

export interface KlineResponse {
  bars: KlineData[];
  dataQuality: 'full' | 'missing' | 'invalid_ohlc';
}

export interface QuotesResponse {
  stocks: StockQuote[];
  total: number;
  page: number;
  pageSize: number;
}

export interface InstrumentInfo {
  code: string;
  name: string;
  exchange: string;
  securityType: string;
  status: string;
}

export interface StockProfile {
  code?: string;
  name?: string;
  industry?: string | null;
  listDate?: string | null;
  totalShares?: number | null;
  floatShares?: number | null;
  totalMarketCap?: number | null;
  floatMarketCap?: number | null;
  source?: string;
}

export interface CapitalFlowRow {
  date: string;
  mainNet: number | null;
  mainNetRatio: number | null;
  superLargeNet: number | null;
  largeNet: number | null;
  mediumNet: number | null;
  smallNet: number | null;
}

export interface FinancialRow {
  reportDate: string;
  eps: number | null;
  bps: number | null;
  roe: number | null;
  revenue: number | null;
  netProfit: number | null;
  grossMargin: number | null;
}

export interface DragonTigerRow {
  date: string;
  name: string;
  reason: string;
  netBuy: number | null;
  buy: number | null;
  sell: number | null;
}

export interface NewsRow {
  title: string;
  url: string | null;
  source: string | null;
  publishedAt: string | null;
  summary: string | null;
}

export interface ScreenFilters {
  priceMin?: number;
  priceMax?: number;
  changePercentMin?: number;
  changePercentMax?: number;
  volumeMin?: number;
  volumeMax?: number;
  amountMin?: number;
  amountMax?: number;
  keyword?: string;
}

export type KlinePeriod = '1min' | '5min' | '15min' | '30min' | 'hour' | 'day';

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
   * 获取单只股票实时报价（真实快照不可用时返回最近收盘，带 stale 标记）
   */
  getQuote: async (code: string): Promise<StockQuote> => {
    const res = await apiClient.get<StockQuote>(`/market/quote/${encodeURIComponent(code)}`);
    return res.data;
  },

  /**
   * 获取K线数据
   */
  getKline: async (
    symbol: string,
    period: KlinePeriod = 'day',
    count = 200
  ): Promise<KlineResponse> => {
    const response = await apiClient.get<KlineResponse>('/market/kline', {
      params: { symbol, period, count },
    });
    return response.data;
  },

  /**
   * 标的搜索（代码 / 名称）
   */
  searchInstruments: async (search: string, limit = 20): Promise<InstrumentInfo[]> => {
    const res = await apiClient.get<InstrumentInfo[]>('/market/instruments', {
      params: { search, limit },
    });
    return res.data;
  },

  /** 个股概览（行业/板块、市值、上市日期） */
  getStockProfile: async (code: string): Promise<StockProfile> => {
    const res = await apiClient.get<StockProfile>(`/market/stock/${encodeURIComponent(code)}`);
    return res.data;
  },

  getCapitalFlow: async (code: string, limit = 30): Promise<CapitalFlowRow[]> => {
    const res = await apiClient.get<CapitalFlowRow[]>('/market/capital-flow', {
      params: { code, limit },
    });
    return res.data;
  },

  getFinancials: async (code: string, limit = 12): Promise<FinancialRow[]> => {
    const res = await apiClient.get<FinancialRow[]>('/market/financials', {
      params: { code, limit },
    });
    return res.data;
  },

  getDragonTiger: async (code: string, limit = 20): Promise<DragonTigerRow[]> => {
    const res = await apiClient.get<DragonTigerRow[]>('/market/dragon-tiger', {
      params: { code, limit },
    });
    return res.data;
  },

  getNews: async (code: string, limit = 20): Promise<NewsRow[]> => {
    const res = await apiClient.get<NewsRow[]>('/market/news', {
      params: { code, limit },
    });
    return res.data;
  },

  /** 行情缓存新鲜度（ms 时间戳；0 表示暂无快照） */
  getFreshness: async (): Promise<{ quotesTs: number }> => {
    const res = await apiClient.get<{ quotesTs: number }>('/market/freshness');
    return res.data;
  },

  /** 条件选股（基于全市场实时快照） */
  screen: async (
    filters: ScreenFilters,
    options?: { limit?: number; sortBy?: 'price' | 'changePercent' | 'volume' | 'amount'; sortOrder?: 'asc' | 'desc' }
  ): Promise<{ stocks: StockQuote[]; total: number }> => {
    const res = await apiClient.post<{ stocks: StockQuote[]; total: number }>('/market/screen', {
      filters,
      limit: options?.limit ?? 50,
      sortBy: options?.sortBy ?? 'changePercent',
      sortOrder: options?.sortOrder ?? 'desc',
    });
    return res.data;
  },

  /** 为单只股票按需落库（日K + 资金流 + 财务 + 新闻） */
  refresh: async (
    code: string
  ): Promise<{ code: string; daily: number; capitalFlow: number; financials: number; news: number }> => {
    const res = await apiClient.post<{
      code: string;
      daily: number;
      capitalFlow: number;
      financials: number;
      news: number;
    }>(`/market/refresh/${encodeURIComponent(code)}`);
    return res.data;
  },
};

