import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { marketSocket, type WsPrivateEvent, type WsStatus } from '@/lib/ws/marketSocket';

/**
 * 订阅模拟交易私有 WS 事件（``trade.fill``）。
 * 鉴权连接后，后台撮合成交会推送并触发 onFill，用于刷新账户/持仓/委托。
 */
export function useSimTradeSocket(onFill: (payload: unknown) => void) {
  const token = useAuthStore((s) => s.token);
  const [status, setStatus] = useState<WsStatus>('idle');
  const [lastFillAt, setLastFillAt] = useState<number | null>(null);

  useEffect(() => {
    if (!token) return;
    marketSocket.connect(token);
    const offStatus = marketSocket.onStatus(setStatus);
    const offPrivate = marketSocket.onPrivate((event: WsPrivateEvent) => {
      if (event.type !== 'trade.fill') return;
      setLastFillAt(event.timestamp);
      onFill(event.payload);
    });
    return () => {
      offPrivate();
      offStatus();
    };
  }, [token, onFill]);

  return { status, lastFillAt };
}
