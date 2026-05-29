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
            // 失败时重试 3 次
            retry: 3,
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
            // 失败时重试 1 次
            retry: 1,
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

