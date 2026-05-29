import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/useAuthStore';
import { marketSocket, type WsStatus, type WsUpdate } from '@/lib/ws/marketSocket';

/**
 * 订阅一组行情主题（如 `['market.indices', 'market.quote.600000.SH']`），
 * 返回连接状态与按 topic 聚合的最新 payload。
 */
export function useMarketSocket(topics: string[]) {
  const token = useAuthStore((s) => s.token);
  const [status, setStatus] = useState<WsStatus>('idle');
  const [data, setData] = useState<Record<string, unknown>>({});
  const topicsKey = topics.join(',');

  useEffect(() => {
    marketSocket.connect(token ?? undefined);
    const offStatus = marketSocket.onStatus(setStatus);
    const offUpdate = marketSocket.onUpdate((update: WsUpdate) => {
      setData((prev) => ({ ...prev, [update.topic]: update.payload }));
    });

    const list = topicsKey ? topicsKey.split(',') : [];
    marketSocket.subscribe(list);

    return () => {
      marketSocket.unsubscribe(list);
      offUpdate();
      offStatus();
    };
  }, [token, topicsKey]);

  return { status, data };
}
