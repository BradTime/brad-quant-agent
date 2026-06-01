import { WS_BASE_URL } from '@/lib/constants';

export type WsStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error';

export interface WsUpdate {
  topic: string;
  payload: unknown;
  timestamp: number;
}

type UpdateHandler = (update: WsUpdate) => void;
type StatusHandler = (status: WsStatus) => void;

const HEARTBEAT_MS = 30_000;
const PONG_TIMEOUT_MS = 10_000;
const MAX_BACKOFF_MS = 30_000;
const MAX_RECONNECT_ATTEMPTS = 12;
// 后端在 token 无效/过期时以 1008 关闭；据此停止重连（等待携带新 token 重新 connect）
const WS_CLOSE_AUTH = 1008;

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null ? (value as Record<string, unknown>) : null;
}

/**
 * 单例 WebSocket 客户端：持续自动重连（指数退避）、心跳 ping + pong 超时检测、
 * 断线后自动重新订阅。订阅主题：`market.indices`、`market.quote.<code>`。
 */
class MarketSocket {
  private ws: WebSocket | null = null;
  private token: string | undefined;
  private shouldRun = false;
  private status: WsStatus = 'idle';
  private reconnectAttempts = 0;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly topics = new Set<string>();
  private readonly updateHandlers = new Set<UpdateHandler>();
  private readonly statusHandlers = new Set<StatusHandler>();

  connect(token?: string): void {
    if (this.ws && this.token === token && (this.status === 'open' || this.status === 'connecting')) {
      return;
    }
    this.token = token;
    this.shouldRun = true;
    this.reconnectAttempts = 0; // 新 token / 显式重连：重置退避计数
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.open();
  }

  subscribe(topics: string[]): void {
    let changed = false;
    topics.forEach((t) => {
      if (t && !this.topics.has(t)) {
        this.topics.add(t);
        changed = true;
      }
    });
    if (changed && this.isOpen()) {
      this.send({ type: 'subscribe', payload: { topics } });
    }
  }

  unsubscribe(topics: string[]): void {
    topics.forEach((t) => this.topics.delete(t));
    if (this.isOpen()) {
      this.send({ type: 'unsubscribe', payload: { topics } });
    }
  }

  onUpdate(handler: UpdateHandler): () => void {
    this.updateHandlers.add(handler);
    return () => {
      this.updateHandlers.delete(handler);
    };
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    handler(this.status);
    return () => {
      this.statusHandlers.delete(handler);
    };
  }

  close(): void {
    this.shouldRun = false;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
    this.setStatus('idle');
  }

  private open(): void {
    if (typeof window === 'undefined') return;
    this.setStatus('connecting');
    const url = this.token ? `${WS_BASE_URL}?token=${encodeURIComponent(this.token)}` : WS_BASE_URL;
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch {
      this.setStatus('error');
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.setStatus('open');
      if (this.topics.size > 0) {
        this.send({ type: 'subscribe', payload: { topics: [...this.topics] } });
      }
      this.startHeartbeat();
    };

    ws.onmessage = (event: MessageEvent) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(typeof event.data === 'string' ? event.data : '');
      } catch {
        return;
      }
      const msg = asRecord(parsed);
      if (!msg) return;

      if (msg.type === 'pong') {
        this.clearPongTimer();
        return;
      }

      if (msg.type === 'update' && typeof msg.topic === 'string') {
        const update: WsUpdate = {
          topic: msg.topic,
          payload: msg.payload,
          timestamp: typeof msg.timestamp === 'number' ? msg.timestamp : Date.now(),
        };
        this.updateHandlers.forEach((handler) => handler(update));
      }
    };

    ws.onerror = () => {
      this.setStatus('error');
    };

    ws.onclose = (event: CloseEvent) => {
      this.stopHeartbeat();
      this.ws = null;
      if (event.code === WS_CLOSE_AUTH) {
        // 令牌无效/过期：停止重连，避免用坏 token 无限重试；等待上层用新 token 重新 connect
        this.shouldRun = false;
        this.setStatus('error');
        return;
      }
      this.setStatus('closed');
      if (this.shouldRun) {
        this.scheduleReconnect();
      }
    };
  }

  private isOpen(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  private send(obj: unknown): void {
    if (this.isOpen()) {
      this.ws?.send(JSON.stringify(obj));
    }
  }

  private setStatus(status: WsStatus): void {
    this.status = status;
    this.statusHandlers.forEach((handler) => handler(status));
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.send({ type: 'ping' });
      this.armPongTimer();
    }, HEARTBEAT_MS);
  }

  private armPongTimer(): void {
    this.clearPongTimer();
    this.pongTimer = setTimeout(() => {
      this.ws?.close();
    }, PONG_TIMEOUT_MS);
  }

  private clearPongTimer(): void {
    if (this.pongTimer) {
      clearTimeout(this.pongTimer);
      this.pongTimer = null;
    }
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    this.clearPongTimer();
  }

  private scheduleReconnect(): void {
    if (!this.shouldRun) return;
    if (this.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      // 多次重连仍失败：停止并置错，避免无意义的无限退避循环
      this.shouldRun = false;
      this.setStatus('error');
      return;
    }
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, MAX_BACKOFF_MS);
    this.reconnectAttempts += 1;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = setTimeout(() => this.open(), delay);
  }
}

export const marketSocket = new MarketSocket();
