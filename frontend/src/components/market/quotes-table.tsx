'use client';

import { useRouter } from 'next/navigation';
import type { StockQuote } from '@/lib/api/market';
import { formatQuoteFreshness } from '@/lib/api/quote-selection';
import { formatAmount } from '@/lib/utils/format';
import { cn } from '@/lib/utils';

function changeClass(v: number | null): string {
  if (v === null || v === 0) return 'text-muted-foreground';
  return v > 0 ? 'text-up' : 'text-down';
}

interface QuotesTableProps {
  stocks: StockQuote[];
  emptyText?: string;
}

/** 行情列表（点击行进入个股详情）。A 股惯例红涨绿跌。 */
export function QuotesTable({ stocks, emptyText = '暂无数据' }: QuotesTableProps) {
  const router = useRouter();

  if (stocks.length === 0) {
    return <div className="py-10 text-center text-sm text-muted-foreground">{emptyText}</div>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-xs text-muted-foreground">
            <th className="py-2 text-left font-medium">代码</th>
            <th className="py-2 text-left font-medium">名称</th>
            <th className="py-2 text-right font-medium">现价</th>
            <th className="py-2 text-right font-medium">涨跌幅</th>
            <th className="hidden py-2 text-right font-medium sm:table-cell">成交额</th>
            <th className="py-2 text-right font-medium">状态</th>
          </tr>
        </thead>
        <tbody>
          {stocks.map((s) => (
            <tr
              key={s.code}
              onClick={() => router.push(`/market/${encodeURIComponent(s.code)}`)}
              className="cursor-pointer border-b border-border/60 transition-colors hover:bg-muted/50"
            >
              <td className="py-2 font-mono text-xs text-muted-foreground">{s.code}</td>
              <td className="py-2 font-medium">{s.name}</td>
              <td className={cn('tnum py-2 text-right font-semibold', changeClass(s.change))}>
                {s.price != null ? s.price.toFixed(2) : '—'}
              </td>
              <td className={cn('tnum py-2 text-right font-semibold', changeClass(s.change))}>
                {s.changePercent != null
                  ? `${s.changePercent >= 0 ? '+' : ''}${s.changePercent.toFixed(2)}%`
                  : '—'}
              </td>
              <td className="tnum hidden py-2 text-right text-muted-foreground sm:table-cell">
                {formatAmount(s.amount)}
              </td>
              <td className="py-2 text-right text-xs text-muted-foreground">
                {formatQuoteFreshness(s).text}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
