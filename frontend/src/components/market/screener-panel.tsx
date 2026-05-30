'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Filter } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { QuotesTable } from './quotes-table';
import { SourceNote } from './source-note';
import { marketApi, type ScreenFilters, type StockQuote } from '@/lib/api/market';

function numOrUndef(s: string): number | undefined {
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : undefined;
}

export function ScreenerPanel() {
  const [pctMin, setPctMin] = useState('');
  const [pctMax, setPctMax] = useState('');
  const [priceMin, setPriceMin] = useState('');
  const [priceMax, setPriceMax] = useState('');
  const [amountMinYi, setAmountMinYi] = useState('');
  const [keyword, setKeyword] = useState('');
  const [result, setResult] = useState<{ stocks: StockQuote[]; total: number } | null>(null);

  const run = useMutation({
    mutationFn: () => {
      const filters: ScreenFilters = {
        changePercentMin: numOrUndef(pctMin),
        changePercentMax: numOrUndef(pctMax),
        priceMin: numOrUndef(priceMin),
        priceMax: numOrUndef(priceMax),
        amountMin: numOrUndef(amountMinYi) !== undefined ? numOrUndef(amountMinYi)! * 1e8 : undefined,
        keyword: keyword.trim() || undefined,
      };
      return marketApi.screen(filters, { limit: 50, sortBy: 'changePercent', sortOrder: 'desc' });
    },
    onSuccess: (data) => setResult(data),
  });

  const field = (label: string, value: string, set: (v: string) => void, placeholder = '') => (
    <label className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <input
        value={value}
        onChange={(e) => set(e.target.value)}
        placeholder={placeholder}
        inputMode="decimal"
        className="rounded-lg border border-border bg-background px-2.5 py-1.5 text-sm outline-none focus:border-brand/50"
      />
    </label>
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {field('涨跌幅 ≥ (%)', pctMin, setPctMin, '如 3')}
        {field('涨跌幅 ≤ (%)', pctMax, setPctMax, '如 9')}
        {field('现价 ≥ (元)', priceMin, setPriceMin)}
        {field('现价 ≤ (元)', priceMax, setPriceMax)}
        {field('成交额 ≥ (亿)', amountMinYi, setAmountMinYi, '如 5')}
        {field('名称/代码含', keyword, setKeyword, '如 银行')}
      </div>
      <div className="flex items-center justify-between">
        <SourceNote source="全市场快照" freshness="基于实时快照·盘面筛选" />
        <Button size="sm" onClick={() => run.mutate()} disabled={run.isPending}>
          <Filter className="mr-1.5 h-3.5 w-3.5" />
          {run.isPending ? '筛选中…' : '开始筛选'}
        </Button>
      </div>

      {result && (
        <div>
          <div className="mb-2 text-xs text-muted-foreground">命中 {result.total} 只（展示前 {result.stocks.length} 只）</div>
          <QuotesTable stocks={result.stocks} emptyText="无匹配结果（或实时快照暂不可用）" />
        </div>
      )}
    </div>
  );
}
