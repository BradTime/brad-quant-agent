import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { authApi } from '@/lib/api/auth';
import { marketSocket, type WsStatus, type WsUpdate } from '@/lib/ws/marketSocket';

/**
 * 订阅一组行情主题（如 `['market.indices', 'market.quote.600000.SH']`），
 * 返回连接状态、按 topic 聚合的最新 payload 及其本地接收时间。
 *
 * M20: WS 直连 :8000，握手 JWT 来自同源 Cookie 鉴权的 /auth/ws-ticket（仅内存）。
 */
export function useMarketSocket(topics: string[]) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const [status, setStatus] = useState<WsStatus>('idle');
  const [data, setData] = useState<Record<string, unknown>>({});
  const [receivedAt, setReceivedAt] = useState<Record<string, number>>({});
  const topicsKey = topics.join(',');

  useEffect(() => {
    let cancelled = false;

    async function connect() {
      if (!isAuthenticated) {
        marketSocket.close();
        return;
      }
      try {
        const ticket = await authApi.getWsTicket();
        if (cancelled) return;
        marketSocket.connect(ticket);
      } catch {
        if (!cancelled) marketSocket.close();
      }
    }

    void connect();
    const offStatus = marketSocket.onStatus((nextStatus) => {
      setStatus(nextStatus);
      if (nextStatus !== 'open') {
        setData({});
        setReceivedAt({});
      }
    });
    const offUpdate = marketSocket.onUpdate((update: WsUpdate) => {
      const receivedAtNow = Date.now();
      setData((prev) => ({ ...prev, [update.topic]: update.payload }));
      setReceivedAt((prev) => ({ ...prev, [update.topic]: receivedAtNow }));
    });

    const list = topicsKey ? topicsKey.split(',') : [];
    marketSocket.subscribe(list);

    return () => {
      cancelled = true;
      marketSocket.unsubscribe(list);
      offUpdate();
      offStatus();
    };
  }, [isAuthenticated, topicsKey]);

  return { status, data, receivedAt };
}
