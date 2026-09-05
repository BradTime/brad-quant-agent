'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useMutation } from '@tanstack/react-query';
import { authApi } from '@/lib/api/auth';
import { getApiErrorMessage } from '@/lib/api/errors';
import { validateVerification } from '@/lib/auth-validation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';

export default function VerifyPage() {
  const [error, setError] = useState('');
  const [verified, setVerified] = useState(false);
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const mutation = useMutation({
    mutationFn: authApi.verifyEmail,
    onSuccess: () => setVerified(true),
    onError: (reason: unknown) => {
      setError(getApiErrorMessage(reason, '验证链接无效或已过期'));
    },
  });

  const verify = (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    const token = new URLSearchParams(window.location.search).get('token');
    if (!token) {
      setError('验证链接无效或已过期');
      return;
    }
    const validationError = validateVerification({ name, password, confirmPassword });
    if (validationError) {
      setError(validationError);
      return;
    }
    mutation.mutate({ token, name: name.trim(), password });
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>验证邮箱</CardTitle>
          <CardDescription>完成验证后即可登录账户</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            role="alert"
            aria-live="polite"
            className={error ? 'rounded-md bg-destructive/10 p-3 text-sm text-destructive' : 'sr-only'}
          >
            {error}
          </div>
          {verified && (
            <div role="status" className="rounded-md bg-primary/10 p-3 text-sm text-primary">
              邮箱验证成功，现在可以登录。
            </div>
          )}
          {!verified && (
            <form onSubmit={verify} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">姓名</Label>
                <Input
                  id="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  minLength={1}
                  maxLength={64}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">设置密码</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  minLength={10}
                  maxLength={128}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">确认密码</Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  minLength={10}
                  maxLength={128}
                  required
                />
              </div>
              <Button className="w-full" type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? '验证中...' : '验证邮箱'}
              </Button>
            </form>
          )}
        </CardContent>
        <CardFooter className="justify-center">
          <Link href="/login" className="text-sm text-primary hover:underline">
            返回登录
          </Link>
        </CardFooter>
      </Card>
    </div>
  );
}
