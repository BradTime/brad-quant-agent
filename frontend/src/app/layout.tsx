import type { Metadata } from 'next';
import Script from 'next/script';
import { Fraunces, Hanken_Grotesk, IBM_Plex_Mono } from 'next/font/google';
import { HYDRATION_GUARD_SCRIPT, THEME_INIT_SCRIPT } from '@/lib/hydration-guard';
import './globals.css';
import { ReactQueryProvider } from '@/lib/react-query/provider';
import { ThemeProvider } from '@/components/theme-provider';
import { ErrorBoundary } from '@/components/error-boundary';

const fraunces = Fraunces({
  subsets: ['latin'],
  variable: '--font-fraunces',
  weight: ['400', '600', '700'],
  style: ['normal', 'italic'],
  display: 'swap',
});

const hanken = Hanken_Grotesk({
  subsets: ['latin'],
  variable: '--font-hanken',
  weight: ['400', '500', '600'],
  display: 'swap',
});

const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  variable: '--font-plex-mono',
  weight: ['400', '500'],
  display: 'swap',
});

export const metadata: Metadata = {
  title: '量化投资 Agent 平台',
  description: '基于人工智能的 A 股量化投研终端',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body
        suppressHydrationWarning
        className={`${fraunces.variable} ${hanken.variable} ${plexMono.variable} antialiased`}
      >
        {/* 水合前按持久化偏好设好明暗主题，消除刷新闪烁(FOUC) */}
        <Script id="theme-init" strategy="beforeInteractive">
          {THEME_INIT_SCRIPT}
        </Script>
        {/* 在 React 水合前执行：清理扩展注入的 mpa-* / Grammarly / 密码管理器等属性 */}
        <Script id="hydration-guard" strategy="beforeInteractive">
          {HYDRATION_GUARD_SCRIPT}
        </Script>
        <ErrorBoundary>
          <ReactQueryProvider>
            <ThemeProvider>{children}</ThemeProvider>
          </ReactQueryProvider>
        </ErrorBoundary>
      </body>
    </html>
  );
}
