/**
 * 累积式 SSE 帧解析（纯函数，便于单测）。
 *
 * SSE 帧以空行 `\n\n` 分隔，每帧取 `data:` 行的负载；跨 chunk 的半帧由内部 buffer 暂存，
 * 下次 push 继续拼接。返回的负载已去掉 `data:` 前缀与首尾空白（如 `"[DONE]"` 或 JSON 串）。
 */
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
