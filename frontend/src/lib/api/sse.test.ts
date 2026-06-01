import { describe, it, expect } from 'vitest';
import { createSSEParser } from './sse';

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
