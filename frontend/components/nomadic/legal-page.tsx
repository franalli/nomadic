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
    <main className="bg-slate-50">
      <div className="container mx-auto px-4 py-16">
        <div className="max-w-4xl space-y-12">
          <header className="space-y-2">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Nomadic</p>
            <h1 className="text-3xl font-semibold text-slate-900">{title}</h1>
            <p className="text-slate-700 leading-relaxed">{description}</p>
            {updated ? (
              <p className="text-xs text-slate-500">Last updated {updated}</p>
            ) : null}
          </header>

          <div className="grid gap-6">
            {sections.map((section) => (
              <section
                key={section.title}
                className="space-y-3 rounded-2xl bg-white/90 p-6 shadow-sm ring-1 ring-slate-200"
              >
                <h2 className="text-xl font-semibold text-slate-900">{section.title}</h2>
                <div className="space-y-3 leading-relaxed text-slate-700">{section.body}</div>
              </section>
            ))}
          </div>

          {cta ? (
            <div className="rounded-2xl border border-dashed border-slate-200 bg-white/80 p-6 text-slate-800">
              {cta}
            </div>
          ) : null}
        </div>
      </div>
    </main>
  );
}
