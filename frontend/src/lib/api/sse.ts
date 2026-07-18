/**
 * 累积式 SSE 帧解析（纯函数，便于单测）。
 *
 * SSE 帧以空行 `\n\n` 分隔，每帧取 `data:` 行的负载；跨 chunk 的半帧由内部 buffer 暂存，
 * 下次 push 继续拼接。返回的负载已去掉 `data:` 前缀与首尾空白（如 `"[DONE]"` 或 JSON 串）。
 */

export class StreamInterruptedError extends Error {
  constructor(message = '连接中断：未收到完整结束标记') {
    super(message);
    this.name = 'StreamInterruptedError';
  }
}

export function createSSEParser() {
  let buffer = '';
  return {
    push(chunk: string): string[] {
      buffer += chunk;
      const frames = buffer.split('\n\n');
      buffer = frames.pop() ?? '';
      const out: string[] = [];
      for (const frame of frames) {
        const line = frame.trim();
        if (!line.startsWith('data:')) continue;
        out.push(line.slice(5).trim());
      }
      return out;
    },
  };
}

/**
 * 消费 SSE ReadableStream：逐帧回调；必须收到 `[DONE]` 才算正常结束。
 * - `onPayload` 返回 `'done'` 表示已处理结束标记（与收到 `[DONE]` 等价）
 * - EOF 且未完成 → 抛出 {@link StreamInterruptedError}（Abort 除外）
 */
export async function consumeSSE(
  body: ReadableStream<Uint8Array>,
  onPayload: (payload: string) => void | 'done',
  options?: { signal?: AbortSignal }
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const parser = createSSEParser();
  let completed = false;

  try {
    for (;;) {
      if (options?.signal?.aborted) {
        throw new DOMException('The operation was aborted.', 'AbortError');
      }
      const { done, value } = await reader.read();
      if (done) break;
      for (const payload of parser.push(decoder.decode(value, { stream: true }))) {
        if (payload === '[DONE]') {
          completed = true;
          onPayload(payload);
          return;
        }
        const result = onPayload(payload);
        if (result === 'done') {
          completed = true;
          return;
        }
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      /* ignore */
    }
  }

  if (options?.signal?.aborted) {
    throw new DOMException('The operation was aborted.', 'AbortError');
  }
  if (!completed) {
    throw new StreamInterruptedError();
  }
}
