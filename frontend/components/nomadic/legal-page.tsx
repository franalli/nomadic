'use client';

import { motion } from 'framer-motion';
import type { ReactNode } from 'react';

type LegalSection = {
  title: string;
  body: ReactNode;
};

type LegalPageProps = {
  title: string;
  description: string;
  updated?: string;
  sections: LegalSection[];
  cta?: ReactNode;
};

const HEADER_INITIAL = { opacity: 0, y: 24 };
const FADE_UP_ANIMATE = { opacity: 1, y: 0 };
const HEADER_TRANSITION = { duration: 0.45, ease: 'easeOut' as const };
const HEADER_VIEWPORT = { once: true, amount: 0.5 };

const SECTION_INITIAL = { opacity: 0, y: 28 };
const SECTION_VIEWPORT = { once: true, amount: 0.35 };

const CTA_INITIAL = { opacity: 0, y: 28 };
const CTA_TRANSITION = { duration: 0.45, ease: 'easeOut' as const };
const CTA_VIEWPORT = { once: true, amount: 0.25 };

export function LegalPage({ title, description, updated, sections, cta }: LegalPageProps) {
  return (
    <main className="bg-bg">
      <div className="container mx-auto px-4 py-16">
        <div className="max-w-4xl space-y-12">
          <motion.header
            className="space-y-2"
            initial={HEADER_INITIAL}
            whileInView={FADE_UP_ANIMATE}
            transition={HEADER_TRANSITION}
            viewport={HEADER_VIEWPORT}
          >
            <p className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Nomadic</p>
            <h1 className="text-3xl font-semibold text-foreground">{title}</h1>
            <p className="text-text-soft leading-relaxed">{description}</p>
            {updated ? (
              <p className="text-xs text-muted-foreground">Last updated {updated}</p>
            ) : null}
          </motion.header>

          <div className="grid gap-6">
            {sections.map((section, index) => (
              <motion.section
                key={section.title}
                className="space-y-4 rounded-2xl bg-card/90 p-6 shadow-sm ring-1 ring-border"
                initial={SECTION_INITIAL}
                whileInView={FADE_UP_ANIMATE}
                transition={{ duration: 0.45, ease: 'easeOut', delay: index * 0.08 }}
                viewport={SECTION_VIEWPORT}
              >
                <h2 className="text-xl font-semibold text-foreground">{section.title}</h2>
                <div className="space-y-4 leading-relaxed text-text-soft">{section.body}</div>
              </motion.section>
            ))}
          </div>

          {cta ? (
            <motion.div
              className="rounded-2xl border border-dashed border-border bg-card/80 p-6 text-foreground"
              initial={CTA_INITIAL}
              whileInView={FADE_UP_ANIMATE}
              transition={CTA_TRANSITION}
              viewport={CTA_VIEWPORT}
            >
              {cta}
            </motion.div>
          ) : null}
        </div>
      </div>
    </main>
  );
}
