import { cn } from '@/lib/utils';
import type { QuoteStaleReason } from '@/lib/api/market';

const REASON_LABELS: Record<QuoteStaleReason, string> = {
  last_close: '最近收盘',
  missing_as_of: '不可用',
  missing_cache_refresh: '不可用',
  quote_expired: '快照过期',
  cache_expired: '快照过期',
  unverified_event_time: '行情时间未验证',
  market_closed: '市场休市',
  invalid_price: '不可用',
};

interface SourceNoteProps {
  /** 数据来源，如「东方财富·快照」 */
  source?: string;
  /** 新鲜度说明，如「盘后」「秒级快照·可能延迟」 */
  freshness?: string;
  /** 行情数据自身的 asOf（Unix ms），不是 API/WS 发送时间。 */
  asOf?: number | null;
  /** 后端给出的陈旧/不可成交原因。 */
  staleReason?: QuoteStaleReason | null;
  /** 当前快照是否可用于模拟撮合。 */
  executable?: boolean;
  /** 是否为受限/缺失数据（免费源拿不到） */
  limited?: boolean;
  className?: string;
}

/**
 * 数据面板标题旁的「来源 / 新鲜度」标注（SPEC：每个面板需标注数据来源与新鲜度，
 * 拿不到或延迟的明确写出）。
 */
export function SourceNote({
  source,
  freshness,
  asOf,
  staleReason,
  executable,
  limited,
  className,
}: SourceNoteProps) {
  const warning = limited || executable === false || staleReason != null;
  const formattedAsOf =
    asOf != null
      ? new Intl.DateTimeFormat('zh-CN', {
          timeZone: 'Asia/Shanghai',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        }).format(new Date(asOf))
      : null;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium',
        warning
          ? 'border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400'
          : 'border-border bg-muted/50 text-muted-foreground',
        className
      )}
    >
      {source && <span>{source}</span>}
      {freshness && <span className="opacity-80">· {freshness}</span>}
      {formattedAsOf && <span className="opacity-80">· 数据截至 {formattedAsOf}</span>}
      {staleReason && <span>· {REASON_LABELS[staleReason]}</span>}
      {executable === true && <span>· 实时可成交</span>}
      {limited && <span>· 免费源有限/可能缺失</span>}
    </span>
  );
}
