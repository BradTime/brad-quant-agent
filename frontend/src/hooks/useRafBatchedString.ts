import { useCallback, useEffect, useRef } from 'react';

/** Batch rapid string appends to one callback per animation frame. */
export function useRafBatchedString(onUpdate: (value: string) => void) {
  const accRef = useRef('');
  const rafRef = useRef<number | null>(null);
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  const cancelRaf = useCallback(() => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const flush = useCallback(() => {
    rafRef.current = null;
    onUpdateRef.current(accRef.current);
  }, []);

  const append = useCallback(
    (piece: string) => {
      accRef.current += piece;
      if (rafRef.current == null) {
        rafRef.current = requestAnimationFrame(flush);
      }
    },
    [flush],
  );

  const reset = useCallback(
    (value = '') => {
      cancelRaf();
      accRef.current = value;
      onUpdateRef.current(value);
    },
    [cancelRaf],
  );

  const getAccumulated = useCallback(() => accRef.current, []);

  useEffect(() => cancelRaf, [cancelRaf]);

  return { append, reset, getAccumulated };
}
