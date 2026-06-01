/**
 * 从当前主题的 CSS 变量解析 ECharts 配色。
 * 经一个隐藏探针元素读取 computed color，浏览器会把 `hsl(h s% l%)`（CSS4 空格语法）
 * 归一化为 `rgb(...)`，从而被 ECharts/zrender 正确解析；并随明暗主题自动变化。
 */
function cssVarColor(varName: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  const probe = document.createElement('span');
  probe.style.color = `var(${varName})`;
  probe.style.display = 'none';
  document.body.appendChild(probe);
  const rgb = getComputedStyle(probe).color;
  probe.remove();
  return rgb || fallback;
}

/** rgb(r, g, b) -> rgba(r, g, b, a) */
export function withAlpha(rgb: string, alpha: number): string {
  const m = rgb.match(/^rgba?\(([^)]+)\)/);
  if (!m) return rgb;
  const parts = m[1].split(',').slice(0, 3).map((s) => s.trim());
  return `rgba(${parts.join(', ')}, ${alpha})`;
}

export interface ChartPalette {
  brand: string;
  foreground: string;
  muted: string;
  border: string;
  card: string;
  series: string[];
}

export function getChartPalette(): ChartPalette {
  return {
    brand: cssVarColor('--color-brand', 'rgb(232, 178, 90)'),
    foreground: cssVarColor('--foreground', 'rgb(40, 40, 40)'),
    muted: cssVarColor('--muted-foreground', 'rgb(120, 120, 120)'),
    border: cssVarColor('--border', 'rgb(220, 220, 220)'),
    card: cssVarColor('--card', 'rgb(255, 255, 255)'),
    series: [1, 2, 3, 4, 5].map((i) => cssVarColor(`--chart-${i}`, 'rgb(136, 136, 136)')),
  };
}
