'use client';
export default function AuthCallbackError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen flex items-center justify-center dark bg-zinc-950">
      <div className="text-center">
        <h1 className="text-lg font-bold text-white mb-2">Authentication failed</h1>
        <button onClick={reset} className="text-emerald-400 text-sm mr-3">
          Try again
        </button>
        <a href="/" className="text-emerald-400 text-sm">Return to home</a>
      </div>
    </div>
  );
}
