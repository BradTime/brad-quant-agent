import { cookies } from 'next/headers';
import { forbidden } from 'next/navigation';

const backendUrl = (
  process.env.BACKEND_URL || 'http://127.0.0.1:8000'
).replace(/\/$/, '');

export default async function TrainingAdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const response = await fetch(`${backendUrl}/api/v1/auth/me`, {
    headers: { cookie: cookieStore.toString() },
    cache: 'no-store',
  }).catch(() => null);
  if (!response?.ok) forbidden();
  const body = (await response.json()) as {
    data?: { role?: string };
  };
  if (body.data?.role !== 'admin') forbidden();
  return children;
}
