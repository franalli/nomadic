'use client';

import React from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { preprocessSpecialistLinks } from '@/lib/specialistLinkParser';
import { getSpecialistColorRgb } from '@/lib/specialists';
import { useDocumentStore } from '@/state/documentStore';
import type { DayCard } from '@/types/plan-envelope';

const RETRYABLE_PATTERNS = [
  "couldn't connect",
  'check your internet',
  'took too long',
  'check your connection',
  'too quickly',
  'wait a moment',
  'went wrong on our end',
  'try again in a few',
];

export function isRetryableError(content: string): boolean {
  const lowerContent = content.toLowerCase();
  return RETRYABLE_PATTERNS.some((pattern) => lowerContent.includes(pattern));
}

function extractTextContent(node: React.ReactNode): string {
  if (typeof node === 'string') return node;
  if (Array.isArray(node)) return node.map(extractTextContent).join('');
  if (node && typeof node === 'object' && 'props' in node) {
    const element = node as { props?: { children?: React.ReactNode } };
    return extractTextContent(element.props?.children);
  }
  return '';
}

function findBlockByEntityName(entityName: string, dayCards?: DayCard[]): string | undefined {
  if (!dayCards || !entityName) return undefined;
  const needle = entityName.toLowerCase();
  for (const dayCard of dayCards) {
    for (const block of dayCard.blocks ?? []) {
      if (!block.id || !block.summary) continue;
      if (
        block.summary.toLowerCase().includes(needle) ||
        needle.includes(block.summary.toLowerCase())
      ) {
        return block.id;
      }
    }
  }
  return undefined;
}

const MARKDOWN_COMPONENTS = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-4 last:mb-0 leading-relaxed">{children}</p>
  ),
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-zinc-900 dark:text-emerald-400">{children}</strong>
  ),
  em: ({ children }: { children?: React.ReactNode }) => <em className="italic">{children}</em>,
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="my-2 ml-1 list-none space-y-1.5 first:mt-0 last:mb-0">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="my-2 ml-1 list-decimal space-y-1.5 pl-4 first:mt-0 last:mb-0">
      {children}
    </ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => {
    const text = extractTextContent(children);
    const startsWithEmoji = /^[\p{Emoji_Presentation}\p{Extended_Pictographic}]/u.test(text);

    return (
      <li
        className={`relative pl-4 ${
          !startsWithEmoji
            ? "before:absolute before:left-0 before:top-[0.6em] before:h-1.5 before:w-1.5 before:rounded-full before:bg-zinc-900/60 dark:before:bg-zinc-400/60 before:content-['']"
            : ''
        }`}
      >
        {children}
      </li>
    );
  },
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-zinc-100/80 px-1 py-0.5 font-mono text-sm dark:bg-zinc-800/80">
      {children}
    </code>
  ),
  a: ({ href, children }: { href?: string; children?: React.ReactNode }) => {
    if (href?.startsWith('actcolor:')) {
      const specialistType = href.replace('actcolor:', '');
      const entityName = extractTextContent(children);
      const dayCards = useDocumentStore.getState().document?.day_cards;
      const matchingBlockId = findBlockByEntityName(entityName, dayCards);

      if (!matchingBlockId) {
        return (
          <span
            className="activity-mention font-medium"
            style={{ '--topic-color': getSpecialistColorRgb(specialistType) } as React.CSSProperties}
          >
            {children}
          </span>
        );
      }

      return (
        <button
          type="button"
          className="activity-mention inline cursor-pointer border-0 bg-transparent p-0 font-medium text-inherit hover:underline"
          style={{ '--topic-color': getSpecialistColorRgb(specialistType) } as React.CSSProperties}
          data-specialist={specialistType}
          aria-label="Scroll to activity"
          onClick={() => {
            const element = document.querySelector(`[data-block-id="${matchingBlockId}"]`);
            if (!element) return;
            element.scrollIntoView({ behavior: 'smooth', block: 'center' });
            element.classList.remove('activity-scroll-highlight');
            void (element as HTMLElement).offsetWidth;
            element.classList.add('activity-scroll-highlight');
          }}
        >
          {children}
        </button>
      );
    }

    if (href?.startsWith('specialist:')) {
      const specialistType = href.replace('specialist:', '');
      return (
        <button
          type="button"
          onClick={() => {
            window.dispatchEvent(
              new CustomEvent('specialist-navigate', {
                detail: { specialistType },
              })
            );
          }}
          className="inline cursor-pointer font-semibold text-zinc-900 hover:underline dark:text-emerald-400"
        >
          {children}
        </button>
      );
    }

    return <span className="font-semibold text-zinc-900 dark:text-emerald-400">{children}</span>;
  },
  blockquote: ({ children }: { children?: React.ReactNode }) => (
    <blockquote className="my-2 border-l-2 border-emerald-500/40 pl-3 italic text-zinc-500 dark:text-zinc-400 first:mt-0 last:mb-0">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-3 border-zinc-200/50 dark:border-white/10" />,
  h1: ({ children }: { children?: React.ReactNode }) => (
    <h1 className="mb-2 text-lg font-bold text-zinc-900 first:mt-0 dark:text-white">
      {children}
    </h1>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <h2 className="mb-2 text-base font-semibold text-zinc-900 first:mt-0 dark:text-white">
      {children}
    </h2>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <h3 className="mb-1.5 text-sm font-semibold text-zinc-900 first:mt-0 dark:text-white">
      {children}
    </h3>
  ),
};

export function ChatMessageMarkdown({ content }: { content: string }) {
  return (
    <Markdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
      {preprocessSpecialistLinks(content)}
    </Markdown>
  );
}
