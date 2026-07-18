'use client';

import { useEffect, useRef, useState } from 'react';
import { RequireAuth } from '@/components/auth/require-auth';
import { Sidebar } from './sidebar';
import { Topbar } from './topbar';

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const mainWrapRef = useRef<HTMLDivElement>(null);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 1023px)');
    const update = () => {
      setIsMobile(mq.matches);
      if (!mq.matches) setMobileOpen(false);
    };
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    if (!mobileOpen || !isMobile) return;

    const sidebar = sidebarRef.current;
    if (!sidebar) return;

    const focusables = sidebar.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
    );
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    first?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setMobileOpen(false);
        return;
      }
      if (e.key !== 'Tab' || focusables.length === 0) return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [mobileOpen, isMobile]);

  useEffect(() => {
    if (wasOpenRef.current && !mobileOpen) {
      menuButtonRef.current?.focus();
    }
    wasOpenRef.current = mobileOpen;
  }, [mobileOpen]);

  useEffect(() => {
    const el = mainWrapRef.current;
    if (!el) return;
    if (mobileOpen && isMobile) el.setAttribute('inert', '');
    else el.removeAttribute('inert');
  }, [mobileOpen, isMobile]);

  const closeMobile = () => setMobileOpen(false);

  return (
    <RequireAuth>
      <div className="min-h-screen bg-background text-foreground">
        <Sidebar
          ref={sidebarRef}
          mobileOpen={mobileOpen}
          isMobile={isMobile}
          onClose={closeMobile}
        />
        <div ref={mainWrapRef} className="lg:pl-[260px]">
          <Topbar
            menuButtonRef={menuButtonRef}
            mobileOpen={mobileOpen}
            onMenu={() => setMobileOpen(true)}
          />
          <main className="app-fade-up">{children}</main>
        </div>
      </div>
    </RequireAuth>
  );
}
