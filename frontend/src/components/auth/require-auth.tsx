'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/useAuthStore';

interface RequireAuthProps {
  children: React.ReactNode;
  requiredRole?: 'user' | 'vip' | 'admin';
}

const ROLE_HIERARCHY: Record<string, number> = { user: 1, vip: 2, admin: 3 };

function meetsRole(userRole: string | undefined, requiredRole?: 'user' | 'vip' | 'admin'): boolean {
  if (!requiredRole) return true;
  return (ROLE_HIERARCHY[userRole || 'user'] || 0) >= ROLE_HIERARCHY[requiredRole];
}

/**
 * 权限守卫组件，保护需要认证的路由。
 *
 * 认证状态来自持久化的 Zustand store：服务端渲染时为未登录（无 localStorage），
 * 客户端首帧 store 已从 localStorage 恢复。若直接据此分支渲染，会导致首帧
 * 服务端/客户端 DOM 不一致触发 hydration 报错。因此用 `mounted` 门控：
 * 服务端与客户端首帧都先渲染占位，挂载后再根据真实登录态渲染/跳转。
 */
export function RequireAuth({ children, requiredRole }: RequireAuthProps) {
  const router = useRouter();
  const { isAuthenticated, user } = useAuthStore();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!mounted) return;
    if (!isAuthenticated) {
      router.push('/login');
      return;
    }
    if (!meetsRole(user?.role, requiredRole)) {
      router.push('/dashboard');
    }
  }, [mounted, isAuthenticated, user, requiredRole, router]);

  // 服务端 + 客户端首帧一致（均为占位），避免 hydration 不匹配。
  if (!mounted || !isAuthenticated || !meetsRole(user?.role, requiredRole)) {
    return null;
  }

  return <>{children}</>;
}

