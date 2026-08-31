import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const REFRESH_COOKIE = 'qa_refresh';
const ACCESS_COOKIE = 'qa_access';

const APP_PREFIXES = [
  '/dashboard',
  '/market',
  '/ai',
  '/brief',
  '/sim',
  '/backtest',
  '/strategies',
];

function isAppPath(pathname: string): boolean {
  return APP_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

function hasSessionCookie(request: NextRequest): boolean {
  return Boolean(
    request.cookies.get(REFRESH_COOKIE)?.value || request.cookies.get(ACCESS_COOKIE)?.value,
  );
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const authed = hasSessionCookie(request);

  if (isAppPath(pathname) && !authed) {
    const login = new URL('/login', request.url);
    login.searchParams.set('next', pathname);
    return NextResponse.redirect(login);
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
    '/login',
    '/register',
  ],
};
