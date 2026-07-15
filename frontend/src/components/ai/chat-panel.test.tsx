import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import * as ChatPanelModule from './chat-panel';

const { ChatPanel, MemoryPreferenceForm } = ChatPanelModule;

describe('ChatPanel session and preference controls', () => {
  it('renders standalone AI-page controls for sessions and explicit memories', () => {
    const html = renderToStaticMarkup(<ChatPanel enableDeepResearch />);

    expect(html).toContain('新会话');
    expect(html).toContain('对话历史');
    expect(html).toContain('记忆偏好');
  });

  it('keeps preference management off embedded chat panels', () => {
    const html = renderToStaticMarkup(<ChatPanel compact />);

    expect(html).toContain('新会话');
    expect(html).toContain('对话历史');
    expect(html).not.toContain('记忆偏好');
  });

  it('renders allowlisted preference selects instead of free text inputs', () => {
    const html = renderToStaticMarkup(
      <MemoryPreferenceForm
        memoryKey="answer_style"
        memoryValue="concise"
        saving={false}
        error=""
        onChange={() => undefined}
        onSave={() => undefined}
      />
    );

    expect(html).toContain('aria-label="偏好类型"');
    expect(html).toContain('aria-label="偏好选项"');
    expect(html).not.toContain('<input');
    expect(html).not.toContain('<textarea');
  });
});

describe('ChatPanel race-safe state helpers', () => {
  it('patches only the message with the requested stable id', () => {
    const helpers = ChatPanelModule as unknown as {
      patchDisplayMessageById?: (
        messages: Array<{
          id: string;
          role: 'user' | 'assistant';
          content: string;
        }>,
        id: string,
        patch: { content: string }
      ) => Array<{ id: string; role: 'user' | 'assistant'; content: string }>;
    };
    expect(helpers.patchDisplayMessageById).toBeTypeOf('function');
    const messages = [
      { id: 'user-1', role: 'user' as const, content: '问题' },
      { id: 'assistant-1', role: 'assistant' as const, content: '' },
    ];

    const updated = helpers.patchDisplayMessageById!(messages, 'assistant-1', {
      content: '完整答复',
    });

    expect(updated).toEqual([
      { id: 'user-1', role: 'user', content: '问题' },
      { id: 'assistant-1', role: 'assistant', content: '完整答复' },
    ]);
  });

  it('ignores a stale session load generation', () => {
    const helpers = ChatPanelModule as unknown as {
      applyLoadedSessionByGeneration?: <T>(
        current: T[],
        activeGeneration: number,
        responseGeneration: number,
        loaded: T[]
      ) => T[];
    };
    expect(helpers.applyLoadedSessionByGeneration).toBeTypeOf('function');
    const current = [{ id: 'current' }];
    const stale = [{ id: 'stale' }];

    expect(helpers.applyLoadedSessionByGeneration!(current, 2, 1, stale)).toBe(
      current
    );
    expect(
      helpers.applyLoadedSessionByGeneration!(current, 2, 2, stale)
    ).toEqual(stale);
  });

  it('clears the active session and messages after invalidation', () => {
    const helpers = ChatPanelModule as unknown as {
      recoverInvalidSession?: <T>() => {
        sessionId: null;
        messages: T[];
      };
    };
    expect(helpers.recoverInvalidSession).toBeTypeOf('function');

    expect(helpers.recoverInvalidSession!()).toEqual({
      sessionId: null,
      messages: [],
    });
  });
});
