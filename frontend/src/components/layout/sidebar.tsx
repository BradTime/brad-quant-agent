'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Activity,
  FlaskConical,
  LayoutDashboard,
  Layers,
  Newspaper,
  Sparkles,
  X,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface NavItem {
  href: string;
  label: string;
  en: string;
  icon: typeof LayoutDashboard;
}

const NAV: NavItem[] = [
  { href: '/dashboard', label: '仪表盘', en: 'Overview', icon: LayoutDashboard },
  { href: '/market', label: '看盘', en: 'Markets', icon: Activity },
  { href: '/brief', label: '盘前早报', en: 'Brief', icon: Newspaper },
  { href: '/strategies', label: '策略', en: 'Strategies', icon: Layers },
  { href: '/backtest', label: '回测', en: 'Backtest', icon: FlaskConical },
  { href: '/ai', label: 'AI 问答', en: 'Copilot', icon: Sparkles },
];

interface SidebarProps {
  mobileOpen: boolean;
  onClose: () => void;
}

export function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  const pathname = usePathname() ?? '';

  return (
    <>
      <div
        className={cn(
          'fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden',
          mobileOpen ? 'block' : 'hidden'
        )}
        onClick={onClose}
        aria-hidden
      />
      <aside
        className={cn(
          'app-grain fixed inset-y-0 left-0 z-50 flex w-[260px] flex-col overflow-hidden',
          'bg-sidebar text-sidebar-foreground border-r border-sidebar-border',
          'transition-transform duration-300 lg:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        {/* 暖金光晕 */}
        <div className="pointer-events-none absolute -left-20 -top-20 h-60 w-60 rounded-full bg-brand/20 blur-3xl" />

        {/* 品牌 */}
        <div className="relative flex items-center gap-3 px-6 pb-7 pt-7">
          <span className="grid h-9 w-9 place-items-center rounded-lg border border-brand/40 bg-brand-soft font-display text-lg italic text-brand">
            Q
          </span>
          <div className="leading-tight">
            <div className="font-display text-lg tracking-tight">
              Quant<span className="text-brand">·</span>A
            </div>
            <div className="text-[10px] uppercase tracking-[0.22em] text-sidebar-muted">
              A股投研终端
            </div>
          </div>
          <button
            onClick={onClose}
            className="ml-auto grid h-8 w-8 place-items-center rounded-md text-sidebar-muted transition-colors hover:text-sidebar-foreground lg:hidden"
            aria-label="关闭菜单"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* 导航 */}
        <nav className="relative flex-1 space-y-1 px-3">
          {NAV.map((item) => {
            const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onClose}
                className={cn(
                  'group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors',
                  active
                    ? 'bg-sidebar-elevated text-sidebar-foreground'
                    : 'text-sidebar-muted hover:bg-sidebar-elevated/60 hover:text-sidebar-foreground'
                )}
              >
                {active && (
                  <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-brand shadow-[0_0_12px_var(--color-brand)]" />
                )}
                <Icon
                  className={cn(
                    'h-[18px] w-[18px] transition-colors',
                    active ? 'text-brand' : 'text-sidebar-muted group-hover:text-sidebar-foreground'
                  )}
                  strokeWidth={1.75}
                />
                <span className="font-medium">{item.label}</span>
                <span className="ml-auto text-[10px] uppercase tracking-[0.15em] text-sidebar-muted/50">
                  {item.en}
                </span>
              </Link>
            );
          })}
        </nav>

        {/* 页脚 */}
        <div className="relative border-t border-sidebar-border px-6 py-5">
          <p className="text-[11px] leading-relaxed text-sidebar-muted">
            数据来源公开免费源 · 仅供研究
            <br />
            不构成投资建议
          </p>
        </div>
      </aside>
    </>
  );
}
