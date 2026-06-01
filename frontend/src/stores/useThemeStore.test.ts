import { describe, it, expect, beforeEach } from 'vitest';
import { useThemeStore } from './useThemeStore';

describe('useThemeStore', () => {
  beforeEach(() => {
    useThemeStore.setState({ theme: 'dark' });
  });

  it('toggles between dark and light', () => {
    expect(useThemeStore.getState().theme).toBe('dark');
    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().theme).toBe('light');
    useThemeStore.getState().toggleTheme();
    expect(useThemeStore.getState().theme).toBe('dark');
  });

  it('setTheme sets the theme explicitly', () => {
    useThemeStore.getState().setTheme('light');
    expect(useThemeStore.getState().theme).toBe('light');
  });
});
