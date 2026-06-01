// 部分 vitest/jsdom 环境不把 localStorage 暴露为全局，补一个内存实现，
// 供 zustand persist（如 useThemeStore）在测试中使用。
if (typeof globalThis.localStorage === 'undefined') {
  const store = new Map<string, string>();
  const memoryStorage: Storage = {
    getItem: (key) => (store.has(key) ? (store.get(key) as string) : null),
    setItem: (key, value) => {
      store.set(key, String(value));
    },
    removeItem: (key) => {
      store.delete(key);
    },
    clear: () => {
      store.clear();
    },
    key: (index) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
  };
  globalThis.localStorage = memoryStorage;
}
