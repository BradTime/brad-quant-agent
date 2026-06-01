// Next.js 16 起 eslint-config-next 直接提供 flat config（不再经 FlatCompat/next lint）。
import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypescript from 'eslint-config-next/typescript';

const eslintConfig = [
  { ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts', 'dist/**'] },
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    // react-hooks 7（随 Next 16 引入）的 React-Compiler 取向新规则先降为 warn：
    // - set-state-in-effect：require-auth 的「mounted gate」是规避 SSR/客户端水合不匹配的有意写法
    // - immutability：仅命中策略编辑（Phase 4 占位页），非核心路径
    rules: {
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/immutability': 'warn',
    },
  },
];

export default eslintConfig;
