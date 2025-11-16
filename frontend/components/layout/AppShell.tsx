import { ChatPanel } from "@/components/chat/ChatPanel";
import { BranchPanel } from "@/components/branches/BranchPanel";

export function AppShell() {
  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-4 p-4 md:flex-row">
      <section className="flex-1 rounded-lg bg-white border border-border shadow-sm p-4 flex flex-col">
        <h1 className="mb-3 text-xl font-semibold">Nomadic</h1>
        <p className="text-sm text-slate-500">Your AI-powered trip companion</p>
        <ChatPanel />
      </section>

      <aside className="w-full md:w-80 flex-shrink-0 rounded-lg bg-white border border-border shadow-sm p-4 flex flex-col">
        <h2 className="mb-3 text-sm font-semibold text-slate-600 uppercase tracking-wide">
          Branches
        </h2>
        <BranchPanel />
      </aside>
    </main>
  );
}
