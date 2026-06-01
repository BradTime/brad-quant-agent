import { describe, it, expect } from 'vitest';
import { ma, ema, macd, kdj, rsi, boll } from './indicators';

describe('ma', () => {
  it('fills warmup with null then averages over the window', () => {
    expect(ma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
  });
});

describe('ema', () => {
  it('seeds with first value and applies alpha = 2/(n+1)', () => {
    const out = ema([2, 4, 6, 8], 3); // k = 0.5
    expect(out[0]).toBe(2);
    expect(out[1]).toBeCloseTo(3, 10);
    expect(out[2]).toBeCloseTo(4.5, 10);
    expect(out[3]).toBeCloseTo(6.25, 10);
  });
});

describe('rsi', () => {
  it('is 100 for a monotonically rising series (no losses)', () => {
    const close = Array.from({ length: 16 }, (_, i) => i + 1);
    const out = rsi(close, 14);
    expect(out[0]).toBeNull();
    expect(out[13]).toBeNull();
    expect(out[14]).toBe(100);
  });
});

describe('boll', () => {
  it('collapses upper/lower to the mean when series is constant', () => {
    const close = Array(25).fill(5);
    const { mid, upper, lower } = boll(close, 20, 2);
    expect(mid[18]).toBeNull();
    expect(mid[19]).toBeCloseTo(5, 10);
    expect(upper[24]).toBeCloseTo(5, 10);
    expect(lower[24]).toBeCloseTo(5, 10);
  });
});

describe('macd', () => {
  it('keeps arrays aligned and hist = 2*(dif-dea)', () => {
    const close = [10, 11, 12, 11, 13, 14, 13, 15, 16, 15, 17, 18, 19, 20];
    const { dif, dea, hist } = macd(close);
    expect(dif).toHaveLength(close.length);
    expect(dea).toHaveLength(close.length);
    for (let i = 0; i < close.length; i++) {
      expect(hist[i]).toBeCloseTo((dif[i] - dea[i]) * 2, 10);
    }
  });
});

describe('kdj', () => {
  it('satisfies j = 3k - 2d and seeds the first point at 50', () => {
    const high = [10, 11, 12, 13, 14];
    const low = [9, 9.5, 10, 11, 12];
    const close = [9.5, 10.5, 11.5, 12.5, 13.5];
    const { k, d, j } = kdj(high, low, close, 9);
    expect(k).toHaveLength(5);
    for (let i = 0; i < 5; i++) {
      expect(j[i]).toBeCloseTo(3 * k[i] - 2 * d[i], 10);
    }
    // rsv0 = (9.5-9)/(10-9)*100 = 50 → k0 = d0 = 50
    expect(k[0]).toBeCloseTo(50, 10);
    expect(d[0]).toBeCloseTo(50, 10);
  });
});
