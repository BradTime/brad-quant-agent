// Next.js 16 起 eslint-config-next 直接提供 flat config（不再经 FlatCompat/next lint）。
import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

const eslintConfig = [
  { ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts', 'dist/**'] },
  ...nextCoreWebVitals,
  ...nextTypescript,
];

export default eslintConfig;
