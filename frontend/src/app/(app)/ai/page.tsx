import { MessageSquareText, ScanSearch, ShieldCheck, Sparkles } from 'lucide-react';

const CAPS = [
  { icon: ScanSearch, title: '工具调用取数', desc: 'AI 通过 function calling 调用行情 / K 线 / 选股工具，基于真实数据作答' },
  { icon: MessageSquareText, title: '流式对话', desc: '自然语言问个股、板块、大盘，答案逐字流式返回' },
  { icon: ShieldCheck, title: '合规守卫', desc: '不杜撰、缺数据明说、不输出确定性买卖指令，附免责声明' },
];

export default function AiPage() {
  return (
    <div className="container mx-auto p-6">
      <div className="relative overflow-hidden rounded-2xl border border-border bg-card p-8">
        <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand/10 blur-3xl" />
        <span className="inline-flex items-center gap-1.5 rounded-full border border-brand/40 bg-brand-soft px-3 py-1 text-xs font-medium text-brand">
          <Sparkles className="h-3.5 w-3.5" /> Phase 1/2 · 建设中
        </span>
        <h2 className="mt-4 font-display text-3xl tracking-tight">AI 看盘问答</h2>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          后端 DeepSeek 工具层（<code className="tnum text-foreground">/api/v1/ai/chat</code>）已就绪。对话界面将在此接入，用一句话驱动整个平台。
        </p>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        {CAPS.map(({ icon: Icon, title, desc }) => (
          <div
            key={title}
            className="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-brand/40"
          >
            <span className="grid h-10 w-10 place-items-center rounded-lg bg-brand-soft text-brand">
              <Icon className="h-5 w-5" strokeWidth={1.75} />
            </span>
            <h3 className="mt-3 font-medium">{title}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{desc}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
