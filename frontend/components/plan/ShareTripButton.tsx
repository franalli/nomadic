'use client';

import { Check, Loader2, Share2 } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { apiFetch } from '@/lib/api';
import { DS } from '@/lib/design-system';
import { cn } from '@/lib/utils';

type ShareState = 'idle' | 'loading' | 'copied';

interface ShareTripButtonProps {
  className?: string;
}

export function ShareTripButton({ className }: ShareTripButtonProps) {
  const [state, setState] = useState<ShareState>('idle');
  const { toast } = useToast();
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (resetTimerRef.current) {
      window.clearTimeout(resetTimerRef.current);
    }
  }, []);

  const handleShare = useCallback(async () => {
    if (state === 'loading') return;
    setState('loading');

    try {
      const res = await apiFetch('/api/share', { method: 'POST' });
      if (!res.ok) {
        throw new Error('Could not share trip');
      }

      const data = await res.json();
      const shareUrl = typeof data?.url === 'string' ? data.url : null;
      const title = typeof data?.title === 'string' ? data.title : 'Shared Trip';
      if (!shareUrl) throw new Error('Share URL missing');

      if (navigator.share) {
        try {
          await navigator.share({ title, url: shareUrl });
          setState('idle');
          return;
        } catch {
          // User canceled native share — continue to clipboard fallback.
        }
      }

      await navigator.clipboard.writeText(shareUrl);
      setState('copied');
      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
      }
      resetTimerRef.current = window.setTimeout(() => {
        setState('idle');
        resetTimerRef.current = null;
      }, 2000);
    } catch (err) {
      console.error('Share failed:', err);
      toast('Could not share trip', { type: 'error' });
      setState('idle');
    }
  }, [state, toast]);

  return (
    <button
      type="button"
      onClick={handleShare}
      disabled={state === 'loading'}
      className={cn(
        DS.textSize.micro,
        'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-bold uppercase tracking-widest',
        'text-muted-foreground hover:bg-accent hover:text-foreground',
        'disabled:pointer-events-none disabled:opacity-50',
        className
      )}
      aria-label="Share trip"
    >
      {state === 'loading' ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
      ) : state === 'copied' ? (
        <Check className="h-3.5 w-3.5 text-emerald-500" />
      ) : (
        <Share2 className="h-3.5 w-3.5" />
      )}
      <span>
        {state === 'copied' ? 'Copied' : state === 'loading' ? 'Sharing' : 'Share'}
      </span>
    </button>
  );
}
