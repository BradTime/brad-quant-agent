'use client';

import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { ChevronDown, LogOut, Menu, MonitorCog, Moon, Sun } from 'lucide-react';
import { useAuthStore } from '@/stores/useAuthStore';
import { useThemeStore } from '@/stores/useThemeStore';
import { authApi } from '@/lib/api/auth';

const TITLES: Record<string, [string, string]> = {
  '/dashboard': ['仪表盘', '你的投研总览'],
  '/market': ['看盘', '实时行情与个股'],
  '/strategies': ['策略', '创建与管理量化策略'],
  '/backtest': ['回测', '用历史检验你的想法'],
  '/ai': ['AI 问答', '与你的投研助手对话'],
};

function titleFor(pathname: string): [string, string] {
  const key = Object.keys(TITLES).find(
    (k) => pathname === k || pathname.startsWith(`${k}/`)
  );
  return key ? TITLES[key] : ['量化投资 Agent', ''];
}

export function Topbar({ onMenu }: { onMenu: () => void }) {
  const pathname = usePathname() ?? '';
  const [title, subtitle] = titleFor(pathname);

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-border bg-background/80 px-5 backdrop-blur-md sm:px-8 lg:px-10">
      <button
        onClick={onMenu}
        className="grid h-9 w-9 place-items-center rounded-md border border-border text-muted-foreground transition-colors hover:text-foreground lg:hidden"
        aria-label="打开菜单"
      >
        <Menu className="h-5 w-5" />
      </button>

      <div className="min-w-0">
        <h1 className="font-display text-xl leading-none tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 truncate text-xs text-muted-foreground">{subtitle}</p>}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <ThemeToggle />
        <UserMenu />
      </div>
    </header>
  );
}

function ThemeToggle() {
  const { theme, toggleTheme } = useThemeStore();
  const Icon = theme === 'dark' ? Moon : theme === 'light' ? Sun : MonitorCog;
  const label = theme === 'dark' ? '深色' : theme === 'light' ? '浅色' : '跟随系统';

  return (
    <button
      onClick={toggleTheme}
      title={`主题：${label}（点击切换）`}
      className="grid h-9 w-9 place-items-center rounded-md border border-border text-muted-foreground transition-colors hover:border-brand/50 hover:text-foreground"
      aria-label="切换主题"
    >
      <Icon className="h-[18px] w-[18px]" />
    </button>
  );
}

function UserMenu() {
  const router = useRouter();
  const { user, clearAuth } = useAuthStore();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const name = user?.name || user?.email || '用户';
  const initial = name.slice(0, 1).toUpperCase();

  async function handleLogout() {
    try {
      await authApi.logout();
    } catch {
      /* 忽略登出接口错误，仍清理本地状态 */
    }
    clearAuth();
    router.push('/login');
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-md border border-border py-1 pl-1 pr-2 transition-colors hover:border-brand/50"
      >
        <span className="grid h-7 w-7 place-items-center rounded-full bg-brand text-sm font-semibold text-[hsl(28_45%_12%)]">
          {initial}
        </span>
        <span className="hidden max-w-[120px] truncate text-sm sm:block">{name}</span>
        <ChevronDown className="h-4 w-4 text-muted-foreground" />
      </button>

      {open && (
        <div className="app-fade-up absolute right-0 mt-2 w-56 overflow-hidden rounded-lg border border-border bg-popover shadow-xl">
          <div className="border-b border-border px-4 py-3">
            <p className="truncate text-sm font-medium">{name}</p>
            {user?.email && <p className="truncate text-xs text-muted-foreground">{user.email}</p>}
          </div>
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-destructive transition-colors hover:bg-muted"
          >
            <LogOut className="h-4 w-4" />
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}
