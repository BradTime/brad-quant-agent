'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { marketApi } from '@/lib/api/market';
import { cn } from '@/lib/utils';

/** 标的搜索框：输入代码/名称，下拉匹配项，点击进入个股详情。 */
export function SearchBox({ className }: { className?: string }) {
  const router = useRouter();
  const [term, setTerm] = useState('');
  const [debounced, setDebounced] = useState('');
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(term.trim()), 250);
    return () => clearTimeout(t);
  }, [term]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const { data: results = [] } = useQuery({
    queryKey: ['instruments', debounced],
    queryFn: () => marketApi.searchInstruments(debounced, 10),
    enabled: debounced.length >= 1,
    retry: false,
  });

  const go = (code: string) => {
    setOpen(false);
    setTerm('');
    router.push(`/market/${encodeURIComponent(code)}`);
  };

  return (
    <div ref={boxRef} className={cn('relative', className)}>
      <div className="flex items-center gap-2 rounded-xl border border-border bg-background px-3 py-2.5">
        <Search className="h-4 w-4 text-muted-foreground" />
        <input
          value={term}
          onChange={(e) => {
            setTerm(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && results[0]) go(results[0].code);
          }}
          placeholder="搜索股票代码或名称，如 600000 / 浦发"
          className="flex-1 bg-transparent text-sm outline-none"
        />
      </div>
      {open && debounced.length >= 1 && results.length > 0 && (
        <ul className="absolute z-30 mt-1 max-h-80 w-full overflow-y-auto rounded-xl border border-border bg-popover p-1 shadow-lg">
          {results.map((r) => (
            <li key={r.code}>
              <button
                onClick={() => go(r.code)}
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted"
              >
                <span className="font-medium">{r.name}</span>
                <span className="font-mono text-xs text-muted-foreground">{r.code}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
