'use client';

import { useEffect, useState, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import { authApi } from '@/lib/api/auth';
import { useAuthStore } from '@/stores/useAuthStore';

const noopSubscribe = () => () => {};

function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}

interface RequireAuthProps {
  children: React.ReactNode;
  requiredRole?: 'user' | 'vip' | 'admin';
}

const ROLE_HIERARCHY: Record<string, number> = { user: 1, vip: 2, admin: 3 };

function meetsRole(userRole: string | undefined, requiredRole?: 'user' | 'vip' | 'admin'): boolean {
  if (!requiredRole) return true;
  return (ROLE_HIERARCHY[userRole || 'user'] || 0) >= ROLE_HIERARCHY[requiredRole];
}

function AuthGateFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center" aria-busy="true">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground/30 border-t-brand" />
    </div>
  );
}

/**
 * 客户端权限守卫（M20）。
 *
 * SSR 门控由 middleware 检查 HttpOnly Cookie；此处用 /auth/me 引导用户态，
 * 不再依赖 localStorage JWT hydrate。保留短 loading，避免闪烁。
 */
export function RequireAuth({ children, requiredRole }: RequireAuthProps) {
  const router = useRouter();
  const { isAuthenticated, user, setAuth, clearAuth } = useAuthStore();
  const mounted = useHydrated();
  const [bootstrapped, setBootstrapped] = useState(false);

  useEffect(() => {
    if (!mounted) return;
    let cancelled = false;

    async function bootstrap() {
      try {
        const me = await authApi.getMe();
        if (cancelled) return;
        setAuth(me);
      } catch {
        if (cancelled) return;
        clearAuth();
        router.replace('/login');
      } finally {
        if (!cancelled) setBootstrapped(true);
      }
    }

    void bootstrap();
    return () => {
      cancelled = true;
    };
  }, [mounted, setAuth, clearAuth, router]);

  useEffect(() => {
    if (!bootstrapped || !isAuthenticated) return;
    if (!meetsRole(user?.role, requiredRole)) {
      router.replace('/dashboard');
    }
  }, [bootstrapped, isAuthenticated, user, requiredRole, router]);

  if (!mounted || !bootstrapped) {
    return <AuthGateFallback />;
  }

  if (!isAuthenticated || !meetsRole(user?.role, requiredRole)) {
    return <AuthGateFallback />;
  }

  return <>{children}</>;
}
