'use client';

import { useEffect, useRef, useState } from 'react';
import { Send, Square, Sparkles } from 'lucide-react';
import { streamChat, type ChatMessage } from '@/lib/api/ai';
import { cn } from '@/lib/utils';
import { Markdown } from './markdown';

interface ChatPanelProps {
  /** 注入给模型的上下文（作为 system 消息，不在界面显示），如"当前正在查看 600000.SH 浦发银行" */
  contextHint?: string;
  /** 建议提问（点击直接发送） */
  suggestions?: string[];
  placeholder?: string;
  className?: string;
  /** 紧凑模式（嵌入个股详情侧栏时使用更小的留白） */
  compact?: boolean;
}

interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
}

export function ChatPanel({
  contextHint,
  suggestions = [],
  placeholder = '问问行情、指数、个股、板块…',
  className,
  compact = false,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || streaming) return;
    setInput('');

    const nextDisplay: DisplayMessage[] = [...messages, { role: 'user', content }];
    setMessages([...nextDisplay, { role: 'assistant', content: '' }]);
    setStreaming(true);

    // 后端只接受真实用户输入；历史 assistant 文本不回传，避免客户端伪造模型事实。
    const payload: ChatMessage[] = nextDisplay
      .filter((m) => m.role === 'user')
      .map((m) => ({
        role: 'user',
        content: m.content,
      }));

    const controller = new AbortController();
    abortRef.current = controller;

    let acc = '';
    try {
      await streamChat(payload, {
        signal: controller.signal,
        contextHint,
        onDelta: (piece) => {
          acc += piece;
          setMessages((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = { role: 'assistant', content: acc };
            return copy;
          });
        },
        onError: (msg) => {
          acc = acc || `⚠️ ${msg}`;
          setMessages((prev) => {
            const copy = [...prev];
            copy[copy.length - 1] = { role: 'assistant', content: acc };
            return copy;
          });
        },
      });
    } catch (err) {
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        setMessages((prev) => {
          const copy = [...prev];
          copy[copy.length - 1] = {
            role: 'assistant',
            content: acc || '⚠️ 连接出错，请稍后重试。',
          };
          return copy;
        });
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  const stop = () => {
    abortRef.current?.abort();
    setStreaming(false);
  };

  return (
    <div className={cn('flex h-full flex-col', className)}>
      <div
        ref={scrollRef}
        className={cn('flex-1 space-y-4 overflow-y-auto', compact ? 'p-3' : 'p-4')}
      >
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-soft text-brand">
              <Sparkles className="h-5 w-5" />
            </span>
            <p className="max-w-xs text-sm text-muted-foreground">
              用一句话提问，AI 会调用行情 / K线 / 财务 / 选股工具，基于真实落库数据作答。
            </p>
            {suggestions.length > 0 && (
              <div className="mt-1 flex flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-brand/40 hover:text-foreground"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          messages.map((m, i) => (
            <div
              key={i}
              className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}
            >
              <div
                className={cn(
                  'max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed',
                  m.role === 'user'
                    ? 'whitespace-pre-wrap bg-brand text-brand-foreground'
                    : 'border border-border bg-card text-foreground'
                )}
              >
                {m.role === 'assistant' && m.content ? (
                  <Markdown content={m.content} />
                ) : (
                  m.content || (streaming && i === messages.length - 1 ? '思考中…' : '')
                )}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="border-t border-border p-3">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={1}
            placeholder={placeholder}
            className="max-h-32 flex-1 resize-none rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:border-brand/50"
          />
          {streaming ? (
            <button
              onClick={stop}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-border text-muted-foreground transition-colors hover:text-foreground"
              aria-label="停止"
            >
              <Square className="h-4 w-4" />
            </button>
          ) : (
            <button
              onClick={() => send(input)}
              disabled={!input.trim()}
              className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand text-brand-foreground transition-opacity disabled:opacity-40"
              aria-label="发送"
            >
              <Send className="h-4 w-4" />
            </button>
          )}
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground">
          AI 基于公开免费数据，可能延迟或缺失；仅供研究，不构成投资建议。
        </p>
      </div>
    </div>
  );
}
