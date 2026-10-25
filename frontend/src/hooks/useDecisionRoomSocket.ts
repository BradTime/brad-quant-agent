'use client';

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { authApi } from '@/lib/api/auth';
import { marketSocket } from '@/lib/ws/marketSocket';

export function useDecisionRoomSocket(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    let cancelled = false;
    void authApi
      .getWsTicket()
      .then((ticket) => {
        if (!cancelled) marketSocket.connect(ticket);
      })
      .catch(() => undefined);
    const offPrivate = marketSocket.onPrivate((event) => {
      if (!event.type.startsWith('decision.')) return;
      void queryClient.invalidateQueries({ queryKey: ['decision-room'] });
    });
    return () => {
      cancelled = true;
      offPrivate();
    };
  }, [queryClient]);
}
