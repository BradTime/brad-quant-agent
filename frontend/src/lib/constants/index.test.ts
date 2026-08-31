import { describe, expect, it } from 'vitest';
import { resolveWsBaseUrl } from './index';

describe('resolveWsBaseUrl', () => {
  it('uses the current browser origin when no explicit WebSocket URL is configured', () => {
    expect(
      resolveWsBaseUrl('', {
        protocol: 'https:',
        host: 'quant.example.com',
      }),
    ).toBe('wss://quant.example.com/ws/v1');
  });

  it('preserves an explicit development override', () => {
    expect(
      resolveWsBaseUrl('ws://localhost:8000/ws/v1', {
        protocol: 'https:',
        host: 'quant.example.com',
      }),
    ).toBe('ws://localhost:8000/ws/v1');
  });
});
