'use client';

import { useState } from 'react';
import { RequireAuth } from '@/components/auth/require-auth';
import { Sidebar } from './sidebar';
import { Topbar } from './topbar';

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <RequireAuth>
      <div className="min-h-screen bg-background text-foreground">
        <Sidebar mobileOpen={mobileOpen} onClose={() => setMobileOpen(false)} />
        <div className="lg:pl-[260px]">
          <Topbar onMenu={() => setMobileOpen(true)} />
          <main className="app-fade-up">{children}</main>
        </div>
      </div>
    </RequireAuth>
  );
}
