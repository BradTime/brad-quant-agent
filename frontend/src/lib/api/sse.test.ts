import { describe, it, expect, vi } from 'vitest';
import {
  createSSEParser,
  consumeSSE,
  StreamInterruptedError,
} from './sse';

describe('createSSEParser', () => {
  it('parses multiple complete frames in one chunk', () => {
    const p = createSSEParser();
    expect(p.push('data: a\n\ndata: b\n\n')).toEqual(['a', 'b']);
  });

  it('buffers a half frame across chunks', () => {
    const p = createSSEParser();
    expect(p.push('data: hel')).toEqual([]);
    expect(p.push('lo\n\n')).toEqual(['hello']);
  });

  it('passes through [DONE] and JSON, skips non-data lines', () => {
    const p = createSSEParser();
    expect(p.push(': comment\n\ndata: {"delta":"x"}\n\ndata: [DONE]\n\n')).toEqual([
      '{"delta":"x"}',
      '[DONE]',
    ]);
  });

  it('does not emit a trailing partial frame until terminated', () => {
    const p = createSSEParser();
    expect(p.push('data: 1\n\ndata: 2')).toEqual(['1']);
    expect(p.push('\n\n')).toEqual(['2']);
  });
});

describe('consumeSSE', () => {
  function streamFrom(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    let i = 0;
    return new ReadableStream({
      pull(controller) {
        if (i >= chunks.length) {
          controller.close();
          return;
        }
        controller.enqueue(encoder.encode(chunks[i++]));
      },
    });
  }

  it('resolves when [DONE] is received', async () => {
    const payloads: string[] = [];
    await consumeSSE(streamFrom(['data: {"delta":"a"}\n\ndata: [DONE]\n\n']), (p) => {
      payloads.push(p);
    });
    expect(payloads).toEqual(['{"delta":"a"}', '[DONE]']);
  });

  it('throws StreamInterruptedError on EOF without [DONE]', async () => {
    await expect(
      consumeSSE(streamFrom(['data: {"delta":"a"}\n\n']), () => undefined)
    ).rejects.toBeInstanceOf(StreamInterruptedError);
  });

  it('propagates AbortError when signal is aborted', async () => {
    const ac = new AbortController();
    ac.abort();
    await expect(
      consumeSSE(streamFrom(['data: x\n\ndata: [DONE]\n\n']), () => undefined, {
        signal: ac.signal,
      })
    ).rejects.toMatchObject({ name: 'AbortError' });
  });
});
