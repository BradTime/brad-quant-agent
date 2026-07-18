'use client';

import { useEffect, useState, useSyncExternalStore } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { authApi } from '@/lib/api/auth';
import { getApiErrorMessage } from '@/lib/api/errors';
import { normalizeEmail, validateLogin } from '@/lib/auth-validation';
import { useAuthStore } from '@/stores/useAuthStore';
import type { LoginRequest } from '@/types';

export default function LoginPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { setAuth, isAuthenticated } = useAuthStore();
  const [formData, setFormData] = useState<LoginRequest>({
    email: '',
    password: '',
  });
  const [error, setError] = useState<string>('');
  const registered = useSyncExternalStore(
    () => () => undefined,
    () => new URLSearchParams(window.location.search).get('registered') === '1',
    () => false,
  );
  const notice = registered
    ? '注册请求已受理，请查收验证邮件；本地自动验证环境可直接登录。'
    : '';

  useEffect(() => {
    if (isAuthenticated) {
      router.replace('/dashboard');
    }
  }, [isAuthenticated, router]);

  const loginMutation = useMutation({
    mutationFn: (data: LoginRequest) => authApi.login(data),
    onSuccess: (data) => {
      queryClient.clear();
      setAuth(data.user, data.token, data.refreshToken);
      router.push('/dashboard');
    },
    onError: (error: unknown) => {
      setError(getApiErrorMessage(error, '登录失败，请检查您的邮箱和密码'));
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const validationError = validateLogin(formData);
    if (validationError) {
      setError(validationError);
      return;
    }
    loginMutation.mutate({ ...formData, email: normalizeEmail(formData.email) });
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <CardTitle className="text-2xl font-bold">登录</CardTitle>
          <CardDescription>请输入您的邮箱和密码以继续</CardDescription>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            <div
              role="alert"
              aria-live="polite"
              className={error ? 'rounded-md bg-destructive/10 p-3 text-sm text-destructive' : 'sr-only'}
            >
              {error}
            </div>
            {notice && (
              <div role="status" className="rounded-md bg-primary/10 p-3 text-sm text-primary">
                {notice}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="email">邮箱</Label>
              <Input
                id="email"
                type="email"
                placeholder="name@example.com"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                required
                disabled={loginMutation.isPending}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                placeholder="请输入密码"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                required
                minLength={1}
                maxLength={256}
                disabled={loginMutation.isPending}
              />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col space-y-4">
            <Button type="submit" className="w-full" disabled={loginMutation.isPending}>
              {loginMutation.isPending ? '登录中...' : '登录'}
            </Button>
            <div className="text-center text-sm text-muted-foreground">
              还没有账户？{' '}
              <Link href="/register" className="text-primary hover:underline">
                立即注册
              </Link>
            </div>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}

