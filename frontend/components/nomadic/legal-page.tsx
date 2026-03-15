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

export function LegalPage({ title, description, updated, sections, cta }: LegalPageProps) {
  return (
    <main className="bg-bg">
      <div className="container mx-auto px-4 py-16">
        <div className="max-w-4xl space-y-12">
          <motion.header
            className="space-y-2"
            initial={{ opacity: 0, y: 24 }}
            whileInView={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, ease: 'easeOut' }}
            viewport={{ once: true, amount: 0.5 }}
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
                initial={{ opacity: 0, y: 28 }}
                whileInView={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.45, ease: 'easeOut', delay: index * 0.08 }}
                viewport={{ once: true, amount: 0.35 }}
              >
                <h2 className="text-xl font-semibold text-foreground">{section.title}</h2>
                <div className="space-y-4 leading-relaxed text-text-soft">{section.body}</div>
              </motion.section>
            ))}
          </div>

          {cta ? (
            <motion.div
              className="rounded-2xl border border-dashed border-border bg-card/80 p-6 text-foreground"
              initial={{ opacity: 0, y: 28 }}
              whileInView={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.45, ease: 'easeOut' }}
              viewport={{ once: true, amount: 0.25 }}
            >
              {cta}
            </motion.div>
          ) : null}
        </div>
      </div>
    </main>
  );
}
