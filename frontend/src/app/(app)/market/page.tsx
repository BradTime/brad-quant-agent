import { CandlestickChart, Coins, ListChecks, Newspaper, TrendingUp } from 'lucide-react';

const FEATURES = [
  { icon: CandlestickChart, title: '个股 K 线', desc: '日/分钟多周期，MA/MACD/KDJ/RSI/BOLL 指标叠加' },
  { icon: ListChecks, title: '自选股', desc: '分组管理，实时报价随 WebSocket 推送' },
  { icon: Coins, title: '资金流向', desc: '主力 / 北向资金，板块与个股维度' },
  { icon: Newspaper, title: '新闻 · 龙虎榜', desc: '个股公告与异动榜单，喂给 AI 问答' },
];

export default function MarketPage() {
  return (
    <div className="container mx-auto p-6">
      <div className="relative overflow-hidden rounded-2xl border border-border bg-card p-8">
        <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-brand/10 blur-3xl" />
        <span className="inline-flex items-center gap-1.5 rounded-full border border-brand/40 bg-brand-soft px-3 py-1 text-xs font-medium text-brand">
          <TrendingUp className="h-3.5 w-3.5" /> Phase 1 · 建设中
        </span>
        <h2 className="mt-4 font-display text-3xl tracking-tight">看盘工作台</h2>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          实时行情底座（数据源 + 缓存 + WebSocket 推送）已就绪。个股详情、K 线与自选股看盘界面即将在此呈现。
        </p>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        {FEATURES.map(({ icon: Icon, title, desc }) => (
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
