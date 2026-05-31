import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Theme } from '@/types';

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: 'dark',
      setTheme: (theme) => set({ theme }),
      toggleTheme: () =>
        set((state) => {
          const newTheme: Theme = state.theme === 'dark' ? 'light' : 'dark';
          return { theme: newTheme };
        }),
    }),
    {
      name: 'theme-storage',
    }
  )
);

