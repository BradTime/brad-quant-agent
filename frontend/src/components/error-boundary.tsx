'use client';

import React from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { captureException } from '@/lib/sentry';

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

interface ErrorBoundaryProps {
  children: React.ReactNode;
  fallback?: React.ComponentType<{ error: Error; resetError: () => void }>;
}

export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    if (process.env.NODE_ENV === 'development') {
      console.error('Error caught by boundary:', error, errorInfo);
    }
    captureException(error, { react: errorInfo.componentStack ?? '' });
  }

  resetError = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        const Fallback = this.props.fallback;
        return <Fallback error={this.state.error!} resetError={this.resetError} />;
      }

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
                  {this.state.error?.message || '发生了未知错误'}
                </p>
                {process.env.NODE_ENV === 'development' && this.state.error?.stack && (
                  <pre className="max-h-40 overflow-auto rounded bg-muted p-2 text-xs">
                    {this.state.error.stack}
                  </pre>
                )}
              </div>
            </CardContent>
            <CardFooter className="flex gap-2">
              <Button onClick={this.resetError} variant="outline">
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

    return this.props.children;
  }
}

