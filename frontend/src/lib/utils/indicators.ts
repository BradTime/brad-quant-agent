/**
 * 技术指标计算（纯前端，基于 K 线数组）。
 * 约定：返回数组与输入等长，预热期填 `null`。采用 A 股常见参数与算法口径。
 */

export type Series = (number | null)[];

/** 简单移动平均 MA(n) */
export function ma(values: number[], period: number): Series {
  const out: Series = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

/** 指数移动平均 EMA(n)，alpha = 2/(n+1) */
export function ema(values: number[], period: number): number[] {
  const out: number[] = [];
  const k = 2 / (period + 1);
  let prev = values[0] ?? 0;
  for (let i = 0; i < values.length; i++) {
    prev = i === 0 ? values[0] : values[i] * k + prev * (1 - k);
    out.push(prev);
  }
  return out;
}

/** MACD(12,26,9)：DIF / DEA / 柱（2×(DIF−DEA)，A 股口径） */
export function macd(
  close: number[],
  fast = 12,
  slow = 26,
  signal = 9
): { dif: number[]; dea: number[]; hist: number[] } {
  const emaFast = ema(close, fast);
  const emaSlow = ema(close, slow);
  const dif = close.map((_, i) => emaFast[i] - emaSlow[i]);
  const dea = ema(dif, signal);
  const hist = dif.map((d, i) => (d - dea[i]) * 2);
  return { dif, dea, hist };
}

/** KDJ(9,3,3) */
export function kdj(
  high: number[],
  low: number[],
  close: number[],
  n = 9
): { k: number[]; d: number[]; j: number[] } {
  const k: number[] = [];
  const d: number[] = [];
  const j: number[] = [];
  let prevK = 50;
  let prevD = 50;
  for (let i = 0; i < close.length; i++) {
    const start = Math.max(0, i - n + 1);
    let hh = -Infinity;
    let ll = Infinity;
    for (let s = start; s <= i; s++) {
      hh = Math.max(hh, high[s]);
      ll = Math.min(ll, low[s]);
    }
    const rsv = hh === ll ? 0 : ((close[i] - ll) / (hh - ll)) * 100;
    const curK = (2 / 3) * prevK + (1 / 3) * rsv;
    const curD = (2 / 3) * prevD + (1 / 3) * curK;
    k.push(curK);
    d.push(curD);
    j.push(3 * curK - 2 * curD);
    prevK = curK;
    prevD = curD;
  }
  return { k, d, j };
}

/** RSI(n)，Wilder 平滑 */
export function rsi(close: number[], period = 14): Series {
  const out: Series = [];
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 0; i < close.length; i++) {
    if (i === 0) {
      out.push(null);
      continue;
    }
    const change = close[i] - close[i - 1];
    const gain = Math.max(change, 0);
    const loss = Math.max(-change, 0);
    if (i <= period) {
      avgGain += gain;
      avgLoss += loss;
      if (i === period) {
        avgGain /= period;
        avgLoss /= period;
        out.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
      } else {
        out.push(null);
      }
    } else {
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
      out.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
    }
  }
  return out;
}

/** BOLL(20,2)：中轨=MA(n)，上/下轨=中轨±k×标准差（总体标准差） */
export function boll(
  close: number[],
  period = 20,
  mult = 2
): { mid: Series; upper: Series; lower: Series } {
  const mid: Series = [];
  const upper: Series = [];
  const lower: Series = [];
  for (let i = 0; i < close.length; i++) {
    if (i < period - 1) {
      mid.push(null);
      upper.push(null);
      lower.push(null);
      continue;
    }
    const window = close.slice(i - period + 1, i + 1);
    const mean = window.reduce((a, b) => a + b, 0) / period;
    const variance = window.reduce((a, b) => a + (b - mean) ** 2, 0) / period;
    const sd = Math.sqrt(variance);
    mid.push(mean);
    upper.push(mean + mult * sd);
    lower.push(mean - mult * sd);
  }
  return { mid, upper, lower };
}
