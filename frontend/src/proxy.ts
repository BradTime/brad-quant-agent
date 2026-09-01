import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const REFRESH_COOKIE = 'qa_refresh';
const ACCESS_COOKIE = 'qa_access';
const BACKEND_URL = (
  process.env.BACKEND_URL || 'http://127.0.0.1:8000'
).replace(/\/$/, '');

const APP_PREFIXES = [
  '/dashboard',
  '/market',
  '/ai',
  '/brief',
  '/sim',
  '/backtest',
  '/strategies',
  '/admin',
];

function isAppPath(pathname: string): boolean {
  return APP_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

function hasSessionCookie(request: NextRequest): boolean {
  return Boolean(
    request.cookies.get(REFRESH_COOKIE)?.value || request.cookies.get(ACCESS_COOKIE)?.value,
  );
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const authed = hasSessionCookie(request);

  if (isAppPath(pathname) && !authed) {
    const login = new URL('/login', request.url);
    login.searchParams.set('next', pathname);
    return NextResponse.redirect(login);
  }

  if (pathname.startsWith('/admin') && authed) {
    const response = await fetch(`${BACKEND_URL}/api/v1/auth/me`, {
      headers: { cookie: request.headers.get('cookie') ?? '' },
      cache: 'no-store',
    }).catch(() => null);
    const body = response?.ok
      ? ((await response.json()) as { data?: { role?: string } })
      : null;
    if (body?.data?.role !== 'admin') {
      return NextResponse.json(
        { code: 403, message: '需要管理员权限', data: null },
        { status: 403 }
      );
    }
  }

  if (authed && (pathname === '/login' || pathname === '/register')) {
    return NextResponse.redirect(new URL('/dashboard', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    '/dashboard/:path*',
    '/market/:path*',
    '/ai/:path*',
    '/brief/:path*',
    '/sim/:path*',
    '/backtest/:path*',
    '/strategies/:path*',
    '/admin/:path*',
    '/login',
    '/register',
  ],
};
