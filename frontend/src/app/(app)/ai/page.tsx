'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Sparkles } from 'lucide-react';
import { RequireAuth } from '@/components/auth/require-auth';
import { ChatPanel } from '@/components/ai/chat-panel';

const SUGGESTIONS = [
  '上证、深证、创业板现在多少点？',
  '今天涨幅超过 5% 的股票有哪些？',
  '浦发银行最近的财务摘要怎么样？',
  '600000 最近的资金流如何？',
  '帮我找成交额超过 50 亿的活跃股',
];

function AiChat() {
  const searchParams = useSearchParams();
  const code = searchParams.get('code')?.trim();
  const contextHint = code
    ? `用户从驾驶舱关注标的 ${code} 进入；优先基于该标的取数作答，勿编造数值。`
    : undefined;
  const suggestions = code
    ? [
        `${code} 现在的股价和涨跌幅？`,
        `${code} 最近的财务摘要怎么样？`,
        `${code} 最近资金流如何？`,
        ...SUGGESTIONS.slice(0, 2),
      ]
    : SUGGESTIONS;

  return <ChatPanel suggestions={suggestions} contextHint={contextHint} enableDeepResearch />;
}

export default function AiPage() {
  return (
    <RequireAuth>
      <div className="container mx-auto flex h-[calc(100vh-7rem)] flex-col p-4 lg:p-6">
        <div className="mb-4 flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand">
            <Sparkles className="h-5 w-5" />
          </span>
          <div>
            <h1 className="font-display text-2xl tracking-tight">AI 看盘问答</h1>
            <p className="text-sm text-muted-foreground">
              自然语言提问，AI 调用行情 / K线 / 财务 / 资金流 / 选股 / 回测工具，基于真实落库数据流式作答；
              「深度研究」模式下自主规划并分步调研后成稿
            </p>
          </div>
        </div>

        <div className="flex-1 overflow-hidden rounded-2xl border border-border bg-card">
          <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">加载对话…</div>}>
            <AiChat />
          </Suspense>
        </div>
      </div>
    </RequireAuth>
  );
}
