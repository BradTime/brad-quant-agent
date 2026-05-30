'use client';

import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';

const COMPONENTS: Components = {
  h1: ({ children }) => (
    <h1 className="mb-3 mt-6 border-b border-border pb-2 font-display text-xl tracking-tight first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2.5 mt-6 flex items-center gap-2 font-display text-lg tracking-tight first:mt-0">
      <span className="h-4 w-[3px] rounded-full bg-brand" />
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-4 text-sm font-semibold text-foreground">{children}</h3>
  ),
  p: ({ children }) => <p className="my-2 text-sm leading-relaxed text-foreground/90">{children}</p>,
  ul: ({ children }) => <ul className="my-2 space-y-1.5 pl-5 text-sm leading-relaxed">{children}</ul>,
  ol: ({ children }) => (
    <ol className="my-2 list-decimal space-y-1.5 pl-5 text-sm leading-relaxed">{children}</ol>
  ),
  li: ({ children }) => <li className="marker:text-brand/60">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  em: ({ children }) => <em className="text-muted-foreground">{children}</em>,
  a: ({ children, href }) => (
    <a href={href} target="_blank" rel="noreferrer" className="text-brand underline underline-offset-2">
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-brand/40 bg-brand-soft/30 py-1 pl-3 text-sm text-muted-foreground">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-4 border-border" />,
  code: ({ children, className }) => {
    const inline = !className;
    if (inline) {
      return (
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-[0.8em] text-foreground">
          {children}
        </code>
      );
    }
    return (
      <code className="block overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs leading-relaxed">
        {children}
      </code>
    );
  },
  table: ({ children }) => (
    <div className="my-3 overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-muted/50">{children}</thead>,
  th: ({ children }) => (
    <th className="border-b border-border px-3 py-2 text-left font-medium text-muted-foreground">
      {children}
    </th>
  ),
  td: ({ children }) => <td className="border-b border-border/60 px-3 py-2">{children}</td>,
};

export function Markdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn('text-foreground', className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
