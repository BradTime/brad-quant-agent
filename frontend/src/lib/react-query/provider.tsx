'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { useState } from 'react';

interface ReactQueryProviderProps {
  children: React.ReactNode;
}

export function ReactQueryProvider({ children }: ReactQueryProviderProps) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // 401 不重试，避免过期登录态触发多次无意义请求。
            retry: (failureCount, error) => {
              const code =
                typeof error === 'object' && error !== null && 'code' in error
                  ? Number((error as { code?: unknown }).code)
                  : undefined;
              if (code === 401) return false;
              return failureCount < 2;
            },
            // 5 分钟后数据过期
            staleTime: 5 * 60 * 1000,
            // 缓存时间 10 分钟
            gcTime: 10 * 60 * 1000,
            // 窗口重新获得焦点时重新获取数据
            refetchOnWindowFocus: true,
            // 网络重新连接时重新获取数据
            refetchOnReconnect: true,
          },
          mutations: {
            retry: false,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {process.env.NODE_ENV === 'development' && <ReactQueryDevtools initialIsOpen={false} />}
    </QueryClientProvider>
  );
}

