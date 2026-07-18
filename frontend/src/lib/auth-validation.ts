import type { LoginRequest } from '@/types';

const CONTROL_OR_SPACE = /[\s\u0000-\u001f\u007f]/;
const CONTROL = /[\u0000-\u001f\u007f]/;

export interface RegistrationFields extends LoginRequest {
  name: string;
  confirmPassword: string;
}

export interface VerificationFields {
  name: string;
  password: string;
  confirmPassword: string;
}

export function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

function passwordBoundaryError(password: string): string | null {
  if (password.length < 10 || password.length > 128) {
    return '密码长度必须为 10 到 128 个字符';
  }
  if (CONTROL_OR_SPACE.test(password)) {
    return '密码不能包含空白或控制字符';
  }
  return null;
}

export function validateLogin(fields: LoginRequest): string | null {
  if (!normalizeEmail(fields.email)) return '请输入有效邮箱';
  if (!fields.password) return '密码不能为空';
  if (fields.password.length > 256) return '密码不能超过 256 个字符';
  if (CONTROL.test(fields.password)) return '密码不能包含控制字符';
  return null;
}

export function validateRegistration(fields: RegistrationFields): string | null {
  if (!normalizeEmail(fields.email)) return '请输入有效邮箱';
  return validateVerification(fields);
}

export function validateVerification(fields: VerificationFields): string | null {
  const passwordError = passwordBoundaryError(fields.password);
  if (passwordError) return passwordError;
  const name = fields.name.trim();
  if (!name || name.length > 64 || CONTROL.test(name)) {
    return '姓名须为 1 到 64 个字符且不能包含控制字符';
  }
  const password = fields.password;
  if (
    !/[a-z]/.test(password) ||
    !/[A-Z]/.test(password) ||
    !/[0-9]/.test(password) ||
    !/[^A-Za-z0-9]/.test(password)
  ) {
    return '密码必须包含大小写字母、数字和特殊字符';
  }
  if (password !== fields.confirmPassword) return '两次输入的密码不一致';
  return null;
}
