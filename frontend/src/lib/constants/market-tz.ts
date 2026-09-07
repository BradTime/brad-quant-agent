/** A-share market timezone (Asia/Shanghai). */
export const MARKET_TZ = 'Asia/Shanghai';

/** Calendar date key (YYYY-MM-DD) in the market timezone. */
export function marketDateKey(date = new Date()): string {
  return date.toLocaleDateString('en-CA', { timeZone: MARKET_TZ });
}
