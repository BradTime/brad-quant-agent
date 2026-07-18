'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Brain,
  History,
  MessageSquare,
  Plus,
  Send,
  Sparkles,
  Square,
  Telescope,
  Trash2,
} from 'lucide-react';
import {
  deleteChatSession,
  deleteUserMemory,
  getChatSession,
  ChatStreamHttpError,
  SESSION_NOT_FOUND_CODE,
  streamChat,
  streamDeepResearch,
  listChatSessions,
  listResearchReports,
  listUserMemories,
  getResearchReport,
  saveUserMemory,
  type ChatMessage,
  type ChatSessionSummary,
  type ResearchStep,
  type ResearchReportSummary,
  type UserMemory,
} from '@/lib/api/ai';
import { useRafBatchedString } from '@/hooks/useRafBatchedString';
import { cn } from '@/lib/utils';
import { Markdown } from './markdown';
import { ResearchPlanCard } from './research-plan';

function fmtTime(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

const MEMORY_OPTIONS = {
  answer_style: {
    label: '回答结构',
    values: {
      concise: '先给结论，再列最关键依据',
      bullet_points: '优先使用简短要点',
      structured: '使用清晰的小标题分段',
    },
  },
  risk_preference: {
    label: '风险表达',
    values: {
      conservative: '突出不确定性与下行情景',
      balanced: '平衡呈现机会与限制',
      aggressive: '讨论高波动情景但不做确定性建议',
    },
  },
  language: {
    label: '语言风格',
    values: {
      simplified_chinese: '简体中文',
      bilingual_terms: '简体中文并附关键英文缩写',
    },
  },
  watch_focus: {
    label: '关注维度',
    values: {
      market_overview: '市场概览',
      fundamentals: '基本面',
      technical: '技术面',
      capital_flow: '资金流',
    },
  },
} as const;

type MemoryKey = keyof typeof MEMORY_OPTIONS;

interface ChatPanelProps {
  /** 界面上下文（后端作为不可信 user 元数据包裹），如"当前正在查看 600000.SH 浦发银行" */
  contextHint?: string;
  /** 建议提问（点击直接发送） */
  suggestions?: string[];
  placeholder?: string;
  className?: string;
  /** 紧凑模式（嵌入个股详情侧栏时使用更小的留白） */
  compact?: boolean;
  /** 开启「深度研究」模式切换（自主多轮规划编排）。默认关闭（嵌入式侧栏不显示）。 */
  enableDeepResearch?: boolean;
}

export interface DisplayMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /** 深度研究：规划者拆出的子问题列表 */
  plan?: string[];
  /** 深度研究：逐步进度 */
  steps?: ResearchStep[];
  mode?: 'chat' | 'research';
}

export function patchDisplayMessageById(
  messages: DisplayMessage[],
  id: string,
  patch: Partial<DisplayMessage>
): DisplayMessage[] {
  return messages.map((message) =>
    message.id === id ? { ...message, ...patch, id: message.id } : message
  );
}

export function applyLoadedSessionByGeneration<T>(
  current: T[],
  activeGeneration: number,
  responseGeneration: number,
  loaded: T[]
): T[] {
  return activeGeneration === responseGeneration ? loaded : current;
}

export function recoverInvalidSession<T>(): {
  sessionId: null;
  messages: T[];
} {
  return { sessionId: null, messages: [] };
}

function newMessageId(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `message-${Date.now()}-${Math.random()}`
  );
}

function memoryValueOptions(key: MemoryKey): Array<[string, string]> {
  return Object.entries(MEMORY_OPTIONS[key].values);
}

function memoryDescription(memory: UserMemory): string {
  const definition = MEMORY_OPTIONS[memory.key as MemoryKey];
  if (!definition) return `${memory.key}: ${memory.value}`;
  const description = (definition.values as Record<string, string>)[
    memory.value
  ];
  return description ? `${definition.label}: ${description}` : definition.label;
}

export function MemoryPreferenceForm({
  memoryKey,
  memoryValue,
  saving,
  error,
  onChange,
  onSave,
}: {
  memoryKey: MemoryKey;
  memoryValue: string;
  saving: boolean;
  error: string;
  onChange: (key: MemoryKey, value: string) => void;
  onSave: () => void;
}) {
  return (
    <div className="space-y-1.5">
      <select
        value={memoryKey}
        onChange={(event) => {
          const key = event.target.value as MemoryKey;
          onChange(key, memoryValueOptions(key)[0][0]);
        }}
        aria-label="偏好类型"
        className="w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-brand/50"
      >
        {Object.entries(MEMORY_OPTIONS).map(([key, definition]) => (
          <option key={key} value={key}>
            {definition.label}
          </option>
        ))}
      </select>
      <select
        value={memoryValue}
        onChange={(event) => onChange(memoryKey, event.target.value)}
        aria-label="偏好选项"
        className="w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs outline-none focus:border-brand/50"
      >
        {memoryValueOptions(memoryKey).map(([value, description]) => (
          <option key={value} value={value}>
            {description}
          </option>
        ))}
      </select>
      {error && <p className="text-[10px] text-destructive">{error}</p>}
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="w-full rounded-lg bg-brand px-2.5 py-1.5 text-xs text-brand-foreground disabled:opacity-40"
      >
        {saving ? '保存中…' : '保存偏好'}
      </button>
    </div>
  );
}

export function ChatPanel({
  contextHint,
  suggestions = [],
  placeholder = '问问行情、指数、个股、板块…',
  className,
  compact = false,
  enableDeepResearch = false,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [loadingSession, setLoadingSession] = useState(false);
  const [chatError, setChatError] = useState('');
  const [deepMode, setDeepMode] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [showSessions, setShowSessions] = useState(false);
  const [researchHistory, setResearchHistory] = useState<
    ResearchReportSummary[]
  >([]);
  const [showResearchHistory, setShowResearchHistory] = useState(false);
  const [memories, setMemories] = useState<UserMemory[]>([]);
  const [showMemories, setShowMemories] = useState(false);
  const [memoryKey, setMemoryKey] = useState<MemoryKey>('answer_style');
  const [memoryValue, setMemoryValue] = useState('concise');
  const [memoryError, setMemoryError] = useState('');
  const [savingMemory, setSavingMemory] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const loadAbortRef = useRef<AbortController | null>(null);
  const activeTurnRef = useRef<{
    userMessageId: string;
    assistantMessageId: string;
  } | null>(null);
  const generationRef = useRef(0);
  const streamTargetRef = useRef<{ id: string; gen: number }>({ id: '', gen: 0 });
  const { append: appendStreamDelta, reset: resetStreamDelta } = useRafBatchedString(
    (content) => {
      const { id, gen } = streamTargetRef.current;
      if (!id || gen !== generationRef.current) return;
      setMessages((current) => patchDisplayMessageById(current, id, { content }));
    },
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const interactedRef = useRef(false);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages]);

  const beginGeneration = useCallback(() => {
    generationRef.current += 1;
    abortRef.current?.abort();
    loadAbortRef.current?.abort();
    const activeTurn = activeTurnRef.current;
    if (activeTurn) {
      setMessages((current) =>
        current.filter(
          (message) =>
            message.id !== activeTurn.userMessageId &&
            message.id !== activeTurn.assistantMessageId
        )
      );
      activeTurnRef.current = null;
    }
    abortRef.current = null;
    loadAbortRef.current = null;
    return generationRef.current;
  }, []);

  useEffect(
    () => () => {
      generationRef.current += 1;
      abortRef.current?.abort();
      loadAbortRef.current?.abort();
    },
    []
  );

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await listChatSessions(50));
    } catch {
      /* ignore */
    }
  }, []);

  const refreshResearchHistory = useCallback(async () => {
    if (!enableDeepResearch) return;
    try {
      setResearchHistory(await listResearchReports(20));
    } catch {
      /* ignore */
    }
  }, [enableDeepResearch]);

  const refreshMemories = useCallback(async () => {
    if (!enableDeepResearch) return;
    try {
      setMemories(await listUserMemories());
    } catch {
      /* ignore */
    }
  }, [enableDeepResearch]);

  useEffect(() => {
    const generation = beginGeneration();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    let disposed = false;
    void (async () => {
      try {
        const [chatRows, researchRows, memoryRows] = await Promise.all([
          listChatSessions(50),
          enableDeepResearch ? listResearchReports(20) : Promise.resolve([]),
          enableDeepResearch ? listUserMemories() : Promise.resolve([]),
        ]);
        if (disposed || generation !== generationRef.current) return;
        setSessions(chatRows);
        if (enableDeepResearch) {
          setResearchHistory(researchRows);
          setMemories(memoryRows);
        }

        // 独立 AI 页刷新后恢复最近普通会话；服务端仍会再次校验 user_id。
        if (enableDeepResearch && chatRows[0] && !interactedRef.current) {
          setLoadingSession(true);
          const detail = await getChatSession(
            chatRows[0].id,
            controller.signal
          );
          if (
            !disposed &&
            generation === generationRef.current &&
            detail &&
            !interactedRef.current
          ) {
            setSessionId(detail.id);
            const loaded = detail.messages.map((message) => ({
              id: message.id,
              role: message.role,
              content: message.content,
              mode: 'chat' as const,
            }));
            setMessages((current) =>
              applyLoadedSessionByGeneration(
                current,
                generationRef.current,
                generation,
                loaded
              )
            );
          }
        }
      } catch (error) {
        if (
          !controller.signal.aborted &&
          generation === generationRef.current
        ) {
          setChatError(
            typeof error === 'object' && error && 'message' in error
              ? String(error.message)
              : '加载会话失败'
          );
        }
      } finally {
        if (generation === generationRef.current) {
          setLoadingSession(false);
          if (loadAbortRef.current === controller) {
            loadAbortRef.current = null;
          }
        }
      }
    })();
    return () => {
      disposed = true;
      controller.abort();
    };
  }, [beginGeneration, enableDeepResearch]);

  const newConversation = () => {
    beginGeneration();
    interactedRef.current = true;
    setStreaming(false);
    setLoadingSession(false);
    setChatError('');
    setSessionId(null);
    setMessages([]);
    setInput('');
    setDeepMode(false);
    setShowSessions(false);
  };

  const loadSession = async (id: string) => {
    const generation = beginGeneration();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    interactedRef.current = true;
    setStreaming(false);
    setLoadingSession(true);
    setChatError('');
    setShowSessions(false);
    try {
      const detail = await getChatSession(id, controller.signal);
      if (!detail || generation !== generationRef.current) return;
      const loaded = detail.messages.map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content,
        mode: 'chat' as const,
      }));
      setSessionId(detail.id);
      setDeepMode(false);
      setMessages((current) =>
        applyLoadedSessionByGeneration(
          current,
          generationRef.current,
          generation,
          loaded
        )
      );
    } catch (error) {
      if (!controller.signal.aborted && generation === generationRef.current) {
        setChatError(
          typeof error === 'object' && error && 'message' in error
            ? String(error.message)
            : '加载会话失败'
        );
      }
    } finally {
      if (generation === generationRef.current) {
        setLoadingSession(false);
        if (loadAbortRef.current === controller) loadAbortRef.current = null;
      }
    }
  };

  const removeSession = async (id: string) => {
    if (
      streaming ||
      loadingSession ||
      !window.confirm('删除此会话及全部消息？此操作不可撤销。')
    )
      return;
    try {
      await deleteChatSession(id);
      setSessions((rows) => rows.filter((row) => row.id !== id));
      if (sessionId === id) {
        setSessionId(null);
        setMessages([]);
      }
    } catch {
      /* ignore */
    }
  };

  const savePreference = async () => {
    if (savingMemory) return;
    setSavingMemory(true);
    setMemoryError('');
    try {
      await saveUserMemory(memoryKey, memoryValue);
      setMemoryKey('answer_style');
      setMemoryValue('concise');
      await refreshMemories();
    } catch (error) {
      const message =
        typeof error === 'object' && error && 'message' in error
          ? String(error.message)
          : '保存偏好失败';
      setMemoryError(message);
    } finally {
      setSavingMemory(false);
    }
  };

  const removePreference = async (id: string) => {
    try {
      await deleteUserMemory(id);
      setMemories((rows) => rows.filter((row) => row.id !== id));
    } catch {
      /* ignore */
    }
  };

  const loadReport = async (id: string) => {
    const generation = beginGeneration();
    interactedRef.current = true;
    setStreaming(false);
    setLoadingSession(true);
    setChatError('');
    setShowResearchHistory(false);
    try {
      const r = await getResearchReport(id);
      if (!r || generation !== generationRef.current) return;
      setMessages((prev) => [
        ...prev,
        { id: newMessageId(), role: 'user', content: r.question },
        {
          id: newMessageId(),
          role: 'assistant',
          content: r.content,
          mode: 'research',
          plan: r.plan,
          steps: r.steps,
        },
      ]);
    } catch (error) {
      if (generation === generationRef.current) {
        setChatError(
          typeof error === 'object' && error && 'message' in error
            ? String(error.message)
            : '加载研究报告失败'
        );
      }
    } finally {
      if (generation === generationRef.current) setLoadingSession(false);
    }
  };

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || streaming || loadingSession || abortRef.current) return;
    const generation = beginGeneration();
    const startingSessionId = sessionId;
    const userMessageId = newMessageId();
    const assistantMessageId = newMessageId();
    interactedRef.current = true;
    setInput('');
    setChatError('');

    const research = deepMode && enableDeepResearch;
    setMessages((current) => [
      ...current,
      { id: userMessageId, role: 'user', content },
      {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        mode: research ? 'research' : 'chat',
        plan: [],
        steps: [],
      },
    ]);
    activeTurnRef.current = { userMessageId, assistantMessageId };
    setStreaming(true);

    // 历史由服务端按 sessionId 加载；客户端只发送本轮 user，避免刷新/重试造成重复。
    const payload: ChatMessage[] = [{ role: 'user', content }];

    const controller = new AbortController();
    abortRef.current = controller;
    streamTargetRef.current = { id: assistantMessageId, gen: generation };
    resetStreamDelta('');

    const patchAssistant = (patch: Partial<DisplayMessage>) => {
      if (generation !== generationRef.current) return;
      setMessages((current) =>
        patchDisplayMessageById(current, assistantMessageId, patch)
      );
    };

    let streamError = '';
    let sessionInvalid = false;
    try {
      if (research) {
        await streamDeepResearch(content, {
          signal: controller.signal,
          contextHint,
          onPlan: (steps) => patchAssistant({ plan: steps }),
          onStep: (step) => {
            if (generation !== generationRef.current) return;
            setMessages((current) => {
              const target = current.find(
                (message) => message.id === assistantMessageId
              );
              return patchDisplayMessageById(current, assistantMessageId, {
                steps: [...(target?.steps ?? []), step],
              });
            });
          },
          onDelta: (piece) => {
            if (generation !== generationRef.current) return;
            appendStreamDelta(piece);
          },
          onError: (msg) => {
            streamError = msg;
          },
        });
        if (streamError) throw new Error(streamError);
        return;
      }
      await streamChat(payload, {
        signal: controller.signal,
        sessionId: startingSessionId ?? undefined,
        contextHint,
        onSession: (id) => {
          if (generation !== generationRef.current) return;
          setSessionId(id);
        },
        onDelta: (piece) => {
          if (generation !== generationRef.current) return;
          appendStreamDelta(piece);
        },
        onError: (msg) => {
          streamError = msg;
        },
        onSessionInvalid: () => {
          sessionInvalid = true;
        },
      });
    } catch (err) {
      if (generation === generationRef.current) {
        activeTurnRef.current = null;
        const invalidSession =
          sessionInvalid ||
          (err instanceof ChatStreamHttpError &&
            err.code === SESSION_NOT_FOUND_CODE);
        if (invalidSession) {
          const recovered = recoverInvalidSession<DisplayMessage>();
          setSessionId(recovered.sessionId);
          setMessages(recovered.messages);
          void refreshSessions();
        } else {
          setMessages((current) =>
            current.filter(
              (message) =>
                message.id !== userMessageId &&
                message.id !== assistantMessageId
            )
          );
        }
        const aborted =
          err instanceof DOMException && err.name === 'AbortError';
        setChatError(
          aborted
            ? '本轮已停止，未保存。'
            : streamError ||
                (err instanceof Error ? err.message : '连接出错，请稍后重试。')
        );
        if (!invalidSession && !research && startingSessionId === null) {
          setSessionId(null);
        }
      }
    } finally {
      if (generation === generationRef.current) {
        activeTurnRef.current = null;
        setStreaming(false);
        if (abortRef.current === controller) abortRef.current = null;
        if (research) {
          void refreshResearchHistory();
        } else {
          void refreshSessions();
        }
      }
    }
  };

  const stop = () => {
    abortRef.current?.abort();
  };

  const controlsBusy = streaming || loadingSession;

  return (
    <div className={cn('flex h-full flex-col', className)}>
      <div
        ref={scrollRef}
        className={cn(
          'flex-1 space-y-4 overflow-y-auto',
          compact ? 'p-3' : 'p-4'
        )}
      >
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-soft text-brand">
              <Sparkles className="h-5 w-5" />
            </span>
            <p className="max-w-xs text-sm text-muted-foreground">
              用一句话提问，AI 会调用行情 / K线 / 财务 /
              选股工具，基于真实落库数据作答。
            </p>
            {suggestions.length > 0 && (
              <div className="mt-1 flex flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    disabled={controlsBusy}
                    className="rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-brand/40 hover:text-foreground disabled:opacity-50"
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
              key={m.id}
              className={cn(
                'flex',
                m.role === 'user' ? 'justify-end' : 'justify-start'
              )}
            >
              <div
                className={cn(
                  'rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed',
                  m.role === 'user'
                    ? 'max-w-[85%] whitespace-pre-wrap bg-brand text-brand-foreground'
                    : 'border border-border bg-card text-foreground',
                  // 研究模式正文较长，放宽气泡宽度以利阅读
                  m.role === 'assistant' && m.mode === 'research'
                    ? 'w-full max-w-[92%]'
                    : 'max-w-[85%]'
                )}
              >
                {m.role === 'assistant' &&
                  m.mode === 'research' &&
                  ((m.plan?.length ?? 0) > 0 || (m.steps?.length ?? 0) > 0) && (
                    <ResearchPlanCard
                      plan={m.plan ?? []}
                      steps={m.steps ?? []}
                      active={streaming && i === messages.length - 1}
                    />
                  )}
                {m.role === 'assistant' && m.content ? (
                  <Markdown content={m.content} />
                ) : (
                  m.content ||
                  (streaming && i === messages.length - 1
                    ? m.mode === 'research'
                      ? '规划中…'
                      : '思考中…'
                    : '')
                )}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="border-t border-border p-3">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          {enableDeepResearch && (
            <div className="inline-flex rounded-lg border border-border p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setDeepMode(false)}
                disabled={controlsBusy}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 transition-colors disabled:opacity-50',
                  !deepMode
                    ? 'bg-brand text-brand-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <MessageSquare className="h-3 w-3" /> 问答
              </button>
              <button
                type="button"
                onClick={() => setDeepMode(true)}
                disabled={controlsBusy}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-2.5 py-1 transition-colors disabled:opacity-50',
                  deepMode
                    ? 'bg-brand text-brand-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                <Telescope className="h-3 w-3" /> 深度研究
              </button>
            </div>
          )}

          <button
            type="button"
            onClick={newConversation}
            className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            <Plus className="h-3 w-3" /> 新会话
          </button>

          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setShowSessions((value) => !value);
                setShowResearchHistory(false);
                setShowMemories(false);
              }}
              disabled={controlsBusy}
              className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
            >
              <History className="h-3 w-3" /> 对话历史
            </button>
            {showSessions && (
              <div className="absolute bottom-full left-0 z-20 mb-1 max-h-72 w-72 overflow-auto rounded-xl border border-border bg-card p-1 shadow-lg">
                {sessions.length === 0 ? (
                  <div className="px-2.5 py-3 text-center text-xs text-muted-foreground">
                    暂无普通对话
                  </div>
                ) : (
                  sessions.map((chatSession) => (
                    <div
                      key={chatSession.id}
                      className={cn(
                        'flex items-center rounded-lg transition-colors hover:bg-muted',
                        sessionId === chatSession.id && 'bg-muted/70'
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => void loadSession(chatSession.id)}
                        disabled={controlsBusy}
                        className="min-w-0 flex-1 px-2.5 py-1.5 text-left disabled:opacity-50"
                      >
                        <div className="truncate text-xs">
                          {chatSession.title}
                        </div>
                        <div className="text-[10px] text-muted-foreground">
                          {fmtTime(chatSession.updatedAt)}
                        </div>
                      </button>
                      <button
                        type="button"
                        onClick={() => void removeSession(chatSession.id)}
                        disabled={controlsBusy}
                        aria-label={`删除会话 ${chatSession.title}`}
                        className="mr-1 grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-background hover:text-destructive disabled:opacity-50"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>

          {enableDeepResearch && researchHistory.length > 0 && (
            <div className="relative">
              <button
                type="button"
                onClick={() => {
                  setShowResearchHistory((value) => !value);
                  setShowSessions(false);
                  setShowMemories(false);
                }}
                disabled={controlsBusy}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                <History className="h-3 w-3" /> 研究历史
              </button>
              {showResearchHistory && (
                <div className="absolute bottom-full left-0 z-20 mb-1 max-h-64 w-72 overflow-auto rounded-xl border border-border bg-card p-1 shadow-lg">
                  {researchHistory.map((h) => (
                    <button
                      key={h.id}
                      type="button"
                      onClick={() => loadReport(h.id)}
                      disabled={controlsBusy}
                      className="block w-full rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-muted disabled:opacity-50"
                    >
                      <div className="truncate text-xs">{h.question}</div>
                      <div className="text-[10px] text-muted-foreground">
                        {fmtTime(h.createdAt)}
                        {h.status !== 'ready' ? ` · ${h.status}` : ''}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {enableDeepResearch && (
            <div className="relative">
              <button
                type="button"
                onClick={() => {
                  setShowMemories((value) => !value);
                  setShowSessions(false);
                  setShowResearchHistory(false);
                }}
                disabled={controlsBusy}
                className="inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
              >
                <Brain className="h-3 w-3" /> 记忆偏好
              </button>
              {showMemories && (
                <div className="absolute bottom-full right-0 z-20 mb-1 w-80 rounded-xl border border-border bg-card p-3 shadow-lg">
                  <div className="mb-2">
                    <div className="text-xs font-medium">
                      主动保存的表达偏好
                    </div>
                    <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">
                      仅用于个性化表达，不作为行情或数值事实；系统不会从模型回答自动提取记忆。
                    </p>
                  </div>
                  <div className="mb-2 max-h-32 space-y-1 overflow-auto">
                    {memories.length === 0 ? (
                      <div className="rounded-lg bg-muted/50 px-2 py-2 text-center text-[10px] text-muted-foreground">
                        暂无偏好
                      </div>
                    ) : (
                      memories.map((memory) => (
                        <div
                          key={memory.id}
                          className="flex items-start gap-2 rounded-lg bg-muted/50 px-2 py-1.5"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="break-words text-[10px] text-muted-foreground">
                              {memoryDescription(memory)}
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => void removePreference(memory.id)}
                            aria-label={`删除偏好 ${memory.key}`}
                            className="grid h-6 w-6 shrink-0 place-items-center rounded text-muted-foreground hover:text-destructive"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                  <MemoryPreferenceForm
                    memoryKey={memoryKey}
                    memoryValue={memoryValue}
                    saving={savingMemory}
                    error={memoryError}
                    onChange={(key, value) => {
                      setMemoryKey(key);
                      setMemoryValue(value);
                    }}
                    onSave={() => void savePreference()}
                  />
                </div>
              )}
            </div>
          )}
        </div>
        {loadingSession && (
          <p className="mb-2 text-xs text-muted-foreground">正在加载会话…</p>
        )}
        {chatError && (
          <p role="alert" className="mb-2 text-xs text-destructive">
            ⚠️ {chatError}
          </p>
        )}
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={controlsBusy}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send(input);
              }
            }}
            rows={1}
            placeholder={
              enableDeepResearch && deepMode
                ? '输入研究问题，AI 自主规划并分步调研后成稿…'
                : placeholder
            }
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
              disabled={!input.trim() || controlsBusy}
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
