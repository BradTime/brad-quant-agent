import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User } from '@/types';

/**
 * M20: session lives in HttpOnly cookies (qa_access / qa_refresh).
 * Persist only the public user profile for UI; never store JWTs in localStorage.
 */
interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  setAuth: (user: User) => void;
  clearAuth: () => void;
  setUser: (user: User) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticated: false,
      setAuth: (user) =>
        set({
          user,
          isAuthenticated: true,
        }),
      clearAuth: () =>
        set({
          user: null,
          isAuthenticated: false,
        }),
      setUser: (user) => set({ user, isAuthenticated: true }),
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        user: state.user,
        isAuthenticated: state.isAuthenticated,
      }),
    }
  )
);
