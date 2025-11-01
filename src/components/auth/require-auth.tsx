'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/useAuthStore';

interface RequireAuthProps {
  children: React.ReactNode;
  requiredRole?: 'user' | 'vip' | 'admin';
}

/**
 * 权限守卫组件
 * 用于保护需要认证的路由
 */
export function RequireAuth({ children, requiredRole }: RequireAuthProps) {
  const router = useRouter();
  const { isAuthenticated, user } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated) {
      router.push('/login');
      return;
    }

    // 检查角色权限
    if (requiredRole) {
      const roleHierarchy: Record<string, number> = {
        user: 1,
        vip: 2,
        admin: 3,
      };

      const userRoleLevel = roleHierarchy[user?.role || 'user'] || 0;
      const requiredRoleLevel = roleHierarchy[requiredRole];

      if (userRoleLevel < requiredRoleLevel) {
        router.push('/dashboard');
        return;
      }
    }
  }, [isAuthenticated, user, requiredRole, router]);

  if (!isAuthenticated) {
    return null;
  }

  if (requiredRole) {
    const roleHierarchy: Record<string, number> = {
      user: 1,
      vip: 2,
      admin: 3,
    };

    const userRoleLevel = roleHierarchy[user?.role || 'user'] || 0;
    const requiredRoleLevel = roleHierarchy[requiredRole];

    if (userRoleLevel < requiredRoleLevel) {
      return null;
    }
  }

  return <>{children}</>;
}

