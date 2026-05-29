'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/stores/useAuthStore';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export default function HomePage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();

  useEffect(() => {
    // 如果已登录，重定向到仪表盘
    if (isAuthenticated) {
      router.push('/dashboard');
    }
  }, [isAuthenticated, router]);

  // 如果未登录，显示首页欢迎页面
  return (
    <div className="flex min-h-screen items-center justify-center p-4 bg-gradient-to-br from-blue-50 to-indigo-100 dark:from-gray-900 dark:to-gray-800">
      <Card className="w-full max-w-2xl">
        <CardHeader className="text-center">
          <CardTitle className="text-4xl font-bold mb-2">量化投资 Agent 平台</CardTitle>
          <CardDescription className="text-lg">
            基于人工智能的量化投资决策支持系统
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="text-center space-y-2">
            <p className="text-muted-foreground">
              提供智能化的投资策略分析、实时市场监控、风险评估和交易建议
            </p>
          </div>
          <div className="flex gap-4 justify-center">
            <Link href="/login">
              <Button size="lg">登录</Button>
            </Link>
            <Link href="/register">
              <Button size="lg" variant="outline">
                注册
              </Button>
            </Link>
          </div>
          <div className="pt-6 border-t text-center">
            <p className="text-sm text-muted-foreground">
              💡 提示：当前需要后端 API 服务才能正常登录。请确保后端服务已启动并配置正确的 API 地址。
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
