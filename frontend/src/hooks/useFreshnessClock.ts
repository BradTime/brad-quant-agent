import { useEffect, useState } from 'react';

const FRESHNESS_TICK_MS = 5_000;

/** Re-render freshness-dependent views and always clear the timer on unmount. */
export function useFreshnessClock(): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), FRESHNESS_TICK_MS);
    return () => window.clearInterval(timer);
  }, []);

  return now;
}
