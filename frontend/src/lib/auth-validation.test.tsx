import { renderToStaticMarkup } from 'react-dom/server';
import { createRoot } from 'react-dom/client';
import { act } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import LoginPage from '@/app/(auth)/login/page';
import RegisterPage from '@/app/(auth)/register/page';
import VerifyPage from '@/app/(auth)/verify/page';
import {
  normalizeEmail,
  validateLogin,
  validateRegistration,
} from './auth-validation';

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  setAuth: vi.fn(),
  mutationConfigs: [] as Array<{ onSuccess?: (data: unknown) => void }>,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mocks.push }),
  useSearchParams: () => ({ get: (key: string) => (key === 'registered' ? '1' : null) }),
}));

vi.mock('@tanstack/react-query', () => ({
  useMutation: (config: { onSuccess?: (data: unknown) => void }) => {
    mocks.mutationConfigs.push(config);
    return { mutate: vi.fn(), isPending: false };
  },
}));

vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: () => ({ setAuth: mocks.setAuth }),
}));

describe('auth validation', () => {
  beforeEach(() => vi.clearAllMocks());

  it('normalizes email without changing passwords', () => {
    expect(normalizeEmail('  USER@Example.COM ')).toBe('user@example.com');
  });

  it('matches backend registration password and name rules', () => {
    expect(
      validateRegistration({
        email: 'user@example.com',
        password: 'weakpassword',
        name: ' Alice ',
        confirmPassword: 'weakpassword',
      }),
    ).toContain('大小写');
    expect(
      validateRegistration({
        email: 'user@example.com',
        password: 'ValidPass1!',
        name: '   ',
        confirmPassword: 'ValidPass1!',
      }),
    ).toContain('姓名');
    expect(
      validateRegistration({
        email: 'user@example.com',
        password: 'ValidPass1!',
        name: ' Alice ',
        confirmPassword: 'ValidPass1!',
      }),
    ).toBeNull();
  });

  it('does not apply complexity checks to login', () => {
    expect(validateLogin({ email: 'user@example.com', password: 'old pass' })).toBeNull();
    expect(validateLogin({ email: 'user@example.com', password: '' })).toContain('不能为空');
    expect(validateLogin({ email: 'user@example.com', password: 'x'.repeat(257) })).toContain('256');
    expect(validateLogin({ email: 'user@example.com', password: 'old\u0000pass' })).toContain('控制');
  });

  it.each(['ÄBCDEFGH1!', 'abcdefghé1!', 'Ａbcdefgh1!'])(
    'uses ASCII password classes for registration: %s',
    (password) => {
      expect(
        validateRegistration({
          email: 'user@example.com',
          password,
          name: 'Alice',
          confirmPassword: password,
        }),
      ).toContain('大小写');
    },
  );

  it('registration success redirects to generic login notice without authenticating', () => {
    renderToStaticMarkup(<RegisterPage />);
    const config = mocks.mutationConfigs.at(-1);
    config?.onSuccess?.({ accepted: true, message: 'generic' });

    expect(mocks.setAuth).not.toHaveBeenCalled();
    expect(mocks.push).toHaveBeenCalledWith('/login?registered=1');
  });

  it('shows the generic registration notice on the login page', async () => {
    window.history.pushState({}, '', '/login?registered=1');
    const container = document.createElement('div');
    const root = createRoot(container);
    await act(async () => root.render(<LoginPage />));
    expect(container.textContent).toContain('注册请求已受理');
    expect(container.textContent).toContain('查收验证邮件');
    await act(async () => root.unmount());
  });

  it('SSR renders an email verification action and alert region', () => {
    const html = renderToStaticMarkup(<VerifyPage />);
    expect(html).toContain('验证邮箱');
    expect(html).toContain('role="alert"');
    expect(html).toContain('id="name"');
    expect(html).toContain('id="password"');
    expect(html).toContain('id="confirmPassword"');
    expect(html).toContain('minLength="10"');
    expect(html).toContain('maxLength="128"');
  });

  it('SSR markup exposes matching bounds and accessible alert regions', () => {
    const login = renderToStaticMarkup(<LoginPage />);
    const register = renderToStaticMarkup(<RegisterPage />);

    expect(login).toContain('minLength="1"');
    expect(login).toContain('maxLength="256"');
    expect(login).toContain('role="alert"');
    expect(register).toContain('minLength="10"');
    expect(register).toContain('maxLength="128"');
    expect(register).toContain('maxLength="64"');
    expect(register).toContain('role="alert"');
  });
});
