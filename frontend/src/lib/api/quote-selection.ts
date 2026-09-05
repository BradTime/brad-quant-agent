import type { WsStatus } from '@/lib/ws/marketSocket';
import { MARKET_TZ } from '@/lib/constants/market-tz';
import type { QuoteStaleReason, StockQuote } from './market';

export interface QuoteFreshnessState {
  asOf: number | null;
  ageMs: number | null;
  maxAgeMs: number;
  stale: boolean;
  staleReason: QuoteStaleReason | null;
  executable: boolean;
}

const NON_EXPIRING_REASONS = new Set<QuoteStaleReason>([
  'last_close',
  'missing_as_of',
  'missing_cache_refresh',
  'invalid_price',
]);

/** Age a retained payload using local elapsed time without changing data asOf. */
export function ageQuote<T extends QuoteFreshnessState>(
  quote: T,
  receivedAt: number,
  now = Date.now()
): T {
  if (quote.ageMs == null || !Number.isFinite(quote.maxAgeMs)) {
    return quote;
  }
  const elapsedMs = receivedAt > 0 ? Math.max(0, now - receivedAt) : 0;
  const effectiveAgeMs = Math.max(0, quote.ageMs) + elapsedMs;
  if (
    effectiveAgeMs <= quote.maxAgeMs ||
    (quote.staleReason != null && NON_EXPIRING_REASONS.has(quote.staleReason))
  ) {
    return quote;
  }
  return {
    ...quote,
    ageMs: effectiveAgeMs,
    stale: true,
    staleReason: 'quote_expired',
    executable: false,
  };
}

function formatAsOf(asOf: number | null): string | null {
  if (asOf == null) return null;
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: MARKET_TZ,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(asOf));
}

/** Human-readable quote state for list and dashboard surfaces. */
export function formatQuoteFreshness(quote: QuoteFreshnessState): {
  label: string;
  asOfText: string | null;
  text: string;
} {
  let label = '不可用';
  if (quote.executable && !quote.stale) {
    label = '实时可成交';
  } else if (quote.staleReason === 'market_closed') {
    label = '市场休市';
  } else if (
    quote.staleReason === 'quote_expired' ||
    quote.staleReason === 'cache_expired'
  ) {
    label = '快照过期';
  } else if (quote.staleReason === 'unverified_event_time') {
    label = '行情时间未验证';
  } else if (quote.staleReason === 'last_close') {
    label = '最近收盘';
  }
  const asOfText = formatAsOf(quote.asOf);
  return {
    label,
    asOfText,
    text: asOfText ? `${label} · ${asOfText}` : label,
  };
}

/** Select the quote shown by the detail page. */
export function selectDisplayQuote(
  httpQuote: StockQuote | undefined,
  wsQuote: StockQuote | undefined,
  wsStatus: WsStatus,
  httpReceivedAt = 0,
  wsReceivedAt = 0,
  now = Date.now()
): StockQuote | undefined {
  const agedHttp = httpQuote ? ageQuote(httpQuote, httpReceivedAt, now) : undefined;
  const agedWs = wsQuote ? ageQuote(wsQuote, wsReceivedAt, now) : undefined;
  if (wsStatus !== 'open' || agedWs?.asOf == null) {
    return agedHttp;
  }
  if (agedHttp?.asOf == null) {
    return agedWs;
  }
  if (agedWs.asOf < agedHttp.asOf) {
    return agedHttp;
  }
  if (agedWs.asOf > agedHttp.asOf) {
    return agedWs;
  }
  // receivedAt 只在相同 data asOf 时裁决状态先后，绝不充当行情时间。
  return wsReceivedAt > httpReceivedAt ? agedWs : agedHttp;
}
