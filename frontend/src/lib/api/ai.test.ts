import { afterEach, describe, expect, it, vi } from 'vitest';

import { streamChat } from './ai';

function sseResponse(...chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }
  );
}

describe('streamChat session frames', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('sends an existing session and reports the early session frame', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(
        sseResponse(
          'data: {"sessionId":"session-1"}\n\n',
          'data: {"delta":"答"}\n\ndata: [DONE]\n\n'
        )
      );
    const onSession = vi.fn();
    const onDelta = vi.fn();

    await streamChat([{ role: 'user', content: '本轮问题' }], {
      sessionId: 'session-1',
      onSession,
      onDelta,
    });

    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toMatchObject({
      sessionId: 'session-1',
      messages: [{ role: 'user', content: '本轮问题' }],
    });
    expect(onSession).toHaveBeenCalledWith('session-1');
    expect(onDelta).toHaveBeenCalledWith('答');
  });

  it('treats EOF without DONE as an interrupted stream', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      sseResponse(
        'data: {"sessionId":"session-new"}\n\n',
        'data: {"delta":"未完成"}\n\n'
      )
    );
    const onError = vi.fn();

    await expect(
      streamChat([{ role: 'user', content: '问题' }], {
        onDelta: vi.fn(),
        onError,
      })
    ).rejects.toThrow('中断');
    expect(onError).toHaveBeenCalledWith(expect.stringContaining('中断'));
  });

  it('propagates SESSION_NOT_FOUND and invokes invalidation callback', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'SESSION_NOT_FOUND',
          message: '会话不存在',
          data: null,
        }),
        {
          status: 404,
          headers: { 'Content-Type': 'application/json' },
        }
      )
    );
    const onError = vi.fn();
    const onSessionInvalid = vi.fn();
    let caught: unknown;

    try {
      await streamChat([{ role: 'user', content: '续聊' }], {
        sessionId: 'deleted-session',
        onDelta: vi.fn(),
        onError,
        onSessionInvalid,
      });
    } catch (error) {
      caught = error;
    }

    expect(caught).toMatchObject({
      message: '会话不存在',
      code: 'SESSION_NOT_FOUND',
      status: 404,
    });
    expect(onError).toHaveBeenCalledWith('会话不存在');
    expect(onSessionInvalid).toHaveBeenCalledOnce();
  });
});
