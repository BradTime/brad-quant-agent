'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // 记录错误到控制台或错误监控服务
    console.error('Application error:', error);
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>出错了</CardTitle>
          <CardDescription>应用遇到了一个错误</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              {error.message || '发生了未知错误'}
            </p>
            {process.env.NODE_ENV === 'development' && error.digest && (
              <p className="text-xs text-muted-foreground">错误 ID: {error.digest}</p>
            )}
          </div>
        </CardContent>
        <CardFooter className="flex gap-2">
          <Button onClick={reset} variant="outline">
            重试
          </Button>
          <Button
            onClick={() => {
              window.location.href = '/';
            }}
          >
            返回首页
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}

