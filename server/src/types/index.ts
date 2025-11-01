export interface User {
  id: string;
  email: string;
  name: string;
  password: string; // 存储时已加密
  avatar?: string;
  role: 'user' | 'vip' | 'admin';
  createdAt: string;
  updatedAt: string;
}

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
  performance?: {
    totalReturn: number;
    totalReturnPercent: number;
    annualReturn: number;
    sharpeRatio: number;
    maxDrawdown: number;
    winRate: number;
    totalTrades: number;
  };
}

export interface ApiResponse<T = unknown> {
  code: number;
  message: string;
  data: T;
  timestamp: number;
}

