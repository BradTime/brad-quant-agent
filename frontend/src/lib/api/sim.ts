import { API_BASE_URL } from '@/lib/constants';
import { useAuthStore } from '@/stores/useAuthStore';
import { apiClient } from './client';
import { createSSEParser, StreamInterruptedError } from './sse';

export interface SimAccount {
  cash: number;
  frozenCash: number;
  initialCash: number;
  marketValue: number;
  totalAssets: number;
  pnl: number;
  pnlPct: number;
}

export interface SimPosition {
  code: string;
  name: string;
  qty: number;
  availableQty: number;
  avgCost: number;
  price: number;
  marketValue: number;
  pnl: number;
  pnlPct: number;
}

export interface SimOrder {
  id: string;
  code: string;
  name: string;
  side: 'buy' | 'sell';
  type: 'limit' | 'market';
  price: number | null;
  qty: number;
  filledQty: number;
  avgFillPrice: number | null;
  status: string;
  reason: string;
  createdAt: string | null;
}

export interface SimTrade {
  id: string;
  code: string;
  name: string;
  side: 'buy' | 'sell';
  price: number;
  qty: number;
  amount: number;
  fee: number;
  tax: number;
  tradedAt: string | null;
}

export interface PlaceOrderRequest {
  code: string;
  side: 'buy' | 'sell';
  type: 'limit' | 'market';
  qty: number;
  price?: number;
}

export const getSimAccount = async (): Promise<SimAccount | null> => {
  const res = await apiClient.get<SimAccount>('/sim/account');
  return res.data;
};

export const getSimPositions = async (): Promise<SimPosition[]> => {
  const res = await apiClient.get<SimPosition[]>('/sim/positions');
  return res.data ?? [];
};

export const listSimOrders = async (limit = 50): Promise<SimOrder[]> => {
  const res = await apiClient.get<SimOrder[]>('/sim/orders', { params: { limit } });
  return res.data ?? [];
};

export const listSimTrades = async (limit = 50): Promise<SimTrade[]> => {
  const res = await apiClient.get<SimTrade[]>('/sim/trades', { params: { limit } });
  return res.data ?? [];
};

export const placeSimOrder = async (body: PlaceOrderRequest): Promise<SimOrder> => {
  const res = await apiClient.post<SimOrder>('/sim/orders', body);
  return res.data as SimOrder;
};

export const cancelSimOrder = async (id: string): Promise<SimOrder | null> => {
  const res = await apiClient.delete<SimOrder>(`/sim/orders/${id}`);
  return res.data;
};

interface ReviewHandlers {
  onDelta: (text: string) => void;
  onError?: (message: string) => void;
  signal?: AbortSignal;
}

/** AI 账户复盘（SSE 流式，delta/[DONE]）。 */
export async function streamSimReview({ onDelta, onError, signal }: ReviewHandlers): Promise<void> {
  const token = useAuthStore.getState().token;
  const res = await fetch(`${API_BASE_URL}/sim/review`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    signal,
  });
  if (!res.ok || !res.body) {
    onError?.(`请求失败（${res.status}）`);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSSEParser();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const payload of parser.push(decoder.decode(value, { stream: true }))) {
      if (payload === '[DONE]') return;
      try {
        const obj = JSON.parse(payload) as { delta?: string; error?: string };
        if (obj.error) {
          onError?.(obj.error);
          return;
        }
        if (obj.delta) onDelta(obj.delta);
      } catch {
        /* skip */
      }
    }
  }
  if (signal?.aborted) return;
  const interrupted = '连接中断：未收到完整结束标记';
  onError?.(interrupted);
  throw new StreamInterruptedError(interrupted);
}
