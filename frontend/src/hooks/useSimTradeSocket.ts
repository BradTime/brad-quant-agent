import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { authApi } from '@/lib/api/auth';
import { marketSocket, type WsPrivateEvent, type WsStatus } from '@/lib/ws/marketSocket';

/**
 * 订阅模拟交易私有 WS 事件（``trade.fill``）。
 * 鉴权连接后，后台撮合成交会推送并触发 onFill，用于刷新账户/持仓/委托。
 *
 * M20: 握手 JWT 来自 /auth/ws-ticket（内存，不落盘）。
 */
export function useSimTradeSocket(onFill: (payload: unknown) => void) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const [status, setStatus] = useState<WsStatus>('idle');
  const [lastFillAt, setLastFillAt] = useState<number | null>(null);

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;

    async function connect() {
      try {
        const ticket = await authApi.getWsTicket();
        if (cancelled) return;
        marketSocket.connect(ticket);
      } catch {
        /* ticket 失败时保持断开，上层可重试 */
      }
    }

    void connect();
    const offStatus = marketSocket.onStatus(setStatus);
    const offPrivate = marketSocket.onPrivate((event: WsPrivateEvent) => {
      if (event.type !== 'trade.fill') return;
      setLastFillAt(event.timestamp);
      onFill(event.payload);
    });
    return () => {
      cancelled = true;
      offPrivate();
      offStatus();
    };
  }, [isAuthenticated, onFill]);

  return { status, lastFillAt };
}
