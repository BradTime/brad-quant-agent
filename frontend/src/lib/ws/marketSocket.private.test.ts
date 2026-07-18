import { describe, expect, it, vi } from 'vitest';

/**
 * 覆盖 WS 私有事件判别：trade.fill 不走 update 路径。
 * 通过直接复现 marketSocket 的消息分发逻辑做纯函数测试，避免 jsdom WebSocket。
 */

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}

function dispatchMessage(
  data: string,
  onUpdate: (u: { topic: string; payload: unknown }) => void,
  onPrivate: (e: { type: string; payload: unknown }) => void
) {
  const msg = asRecord(JSON.parse(data));
  if (!msg || typeof msg.type !== 'string') return;
  if (msg.type === 'update' && typeof msg.topic === 'string') {
    onUpdate({ topic: msg.topic, payload: msg.payload });
    return;
  }
  if (msg.type === 'trade.fill') {
    onPrivate({ type: 'trade.fill', payload: msg.payload });
  }
}

describe('ws private trade.fill protocol', () => {
  it('routes trade.fill to private handler, not update', () => {
    const onUpdate = vi.fn();
    const onPrivate = vi.fn();
    dispatchMessage(
      JSON.stringify({
        type: 'trade.fill',
        payload: { id: 'o1', status: 'filled' },
        timestamp: 1,
      }),
      onUpdate,
      onPrivate
    );
    expect(onUpdate).not.toHaveBeenCalled();
    expect(onPrivate).toHaveBeenCalledWith({
      type: 'trade.fill',
      payload: { id: 'o1', status: 'filled' },
    });
  });

  it('still routes market update by topic', () => {
    const onUpdate = vi.fn();
    const onPrivate = vi.fn();
    dispatchMessage(
      JSON.stringify({
        type: 'update',
        topic: 'market.quote.600000.SH',
        payload: { price: 10 },
        timestamp: 1,
      }),
      onUpdate,
      onPrivate
    );
    expect(onPrivate).not.toHaveBeenCalled();
    expect(onUpdate).toHaveBeenCalledWith({
      topic: 'market.quote.600000.SH',
      payload: { price: 10 },
    });
  });
});
