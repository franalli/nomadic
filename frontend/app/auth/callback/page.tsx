'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect } from 'react';

import { apiFetch } from '@/lib/api';
import { useUserStore } from '@/state/userStore';

function AuthCallbackInner() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    if (!code || !state) {
      router.replace('/');
      return;
    }

    let cancelled = false;
    const complete = async () => {
      try {
        const res = await apiFetch('/api/auth/google/callback', {
          method: 'POST',
          body: JSON.stringify({ code, state }),
        });
        if (!res.ok) throw new Error('Auth callback failed');
        await useUserStore.getState().fetchUser();
      } catch {
        // Ignore and fall back to anonymous mode.
      } finally {
        if (!cancelled) router.replace('/');
      }
    };

    complete();
    return () => {
      cancelled = true;
    };
  }, [router, searchParams]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-zinc-950 text-zinc-400">
      Signing in...
    </div>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen flex items-center justify-center bg-zinc-950 text-zinc-400">
          Signing in...
        </div>
      }
    >
      <AuthCallbackInner />
    </Suspense>
  );
}
