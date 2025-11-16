import { BranchPanel } from '@/components/branches/BranchPanel';
import { ChatPanel } from '@/components/chat/ChatPanel';

export function AppShell() {
  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-4 p-4 md:flex-row">
      <section className="border-border flex flex-1 flex-col rounded-lg border bg-white p-4 shadow-sm">
        <h1 className="mb-3 text-xl font-semibold">Nomadic</h1>
        <p className="text-sm text-slate-500">Your AI-powered trip companion</p>
        <ChatPanel />
      </section>

      <aside className="border-border flex w-full shrink-0 flex-col rounded-lg border bg-white p-4 shadow-sm md:w-80">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">
          Branches
        </h2>
        <BranchPanel />
      </aside>
    </main>
  );
}
