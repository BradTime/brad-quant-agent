import { cn } from '@/lib/utils';

interface SourceNoteProps {
  /** 数据来源，如「东方财富·快照」 */
  source?: string;
  /** 新鲜度说明，如「盘后」「秒级快照·可能延迟」 */
  freshness?: string;
  /** 是否为受限/缺失数据（免费源拿不到） */
  limited?: boolean;
  className?: string;
}

/**
 * 数据面板标题旁的「来源 / 新鲜度」标注（SPEC：每个面板需标注数据来源与新鲜度，
 * 拿不到或延迟的明确写出）。
 */
export function SourceNote({ source, freshness, limited, className }: SourceNoteProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-medium',
        limited
          ? 'border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400'
          : 'border-border bg-muted/50 text-muted-foreground',
        className
      )}
    >
      {source && <span>{source}</span>}
      {freshness && <span className="opacity-80">· {freshness}</span>}
      {limited && <span>· 免费源有限/可能缺失</span>}
    </span>
  );
}
