'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { apiFetch } from '@/lib/api';
import { extractTripPdfData } from '@/lib/pdfData';
import { useUserStore } from '@/state/userStore';
import type { DocumentTripInputs } from '@/types/document';
import type { DayCard } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

interface UseHeaderActionsParams {
  dayCards: DayCard[] | undefined;
  tripInputs: DocumentTripInputs | undefined;
  tiles: Record<string, Tile> | undefined;
  hasDayCards: boolean;
  onMenuClose: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook
// ─────────────────────────────────────────────────────────────────────────────

export function useHeaderActions({
  dayCards,
  tripInputs,
  tiles,
  hasDayCards,
  onMenuClose,
}: UseHeaderActionsParams) {
  const [pdfState, setPdfState] = useState<'idle' | 'loading'>('idle');
  const [shareState, setShareState] = useState<'idle' | 'loading' | 'copied'>('idle');
  const { toast } = useToast();
  const login = useUserStore((s) => s.login);
  const logout = useUserStore((s) => s.logout);
  const shareResetTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (shareResetTimerRef.current) {
      window.clearTimeout(shareResetTimerRef.current);
    }
  }, []);

  const handleNewTrip = useCallback(async () => {
    try {
      await apiFetch('/api/session/new', { method: 'POST' });
      window.location.reload();
    } catch {
      toast('Could not start new trip', { type: 'error' });
    }
  }, [toast]);

  const handlePdfExport = useCallback(async () => {
    if (pdfState === 'loading' || !dayCards?.length) return;
    setPdfState('loading');
    try {
      const [{ pdf }, { saveAs }, { TripPdfDocument }] = await Promise.all([
        import('@react-pdf/renderer'),
        import('file-saver'),
        import('@/components/plan/pdf/TripPdfDocument'),
      ]);
      const data = extractTripPdfData(tripInputs, dayCards, tiles ?? {});
      const blob = await pdf(<TripPdfDocument data={data} />).toBlob();
      const dest = (data.destination || 'Trip').replace(/\s+/g, '-');
      saveAs(blob, `${dest}.pdf`);
    } catch (err) {
      console.error('PDF export failed:', err);
      toast('Could not export PDF', { type: 'error' });
    } finally {
      setPdfState('idle');
      onMenuClose();
    }
  }, [pdfState, tripInputs, dayCards, tiles, toast, onMenuClose]);

  const handleShareTrip = useCallback(async () => {
    if (shareState === 'loading' || !hasDayCards) return;
    setShareState('loading');
    try {
      const res = await apiFetch('/api/share', { method: 'POST' });
      if (!res.ok) throw new Error('Failed to create share link');
      const data = await res.json();
      const shareUrl = typeof data?.url === 'string' ? data.url : null;
      const title = typeof data?.title === 'string' ? data.title : 'Shared Trip';
      if (!shareUrl) throw new Error('Share URL missing');

      if (navigator.share) {
        try {
          await navigator.share({ title, url: shareUrl });
          setShareState('idle');
          onMenuClose();
          return;
        } catch {
          // User canceled native share; continue with clipboard fallback.
        }
      }

      await navigator.clipboard.writeText(shareUrl);
      setShareState('copied');
      if (shareResetTimerRef.current) {
        window.clearTimeout(shareResetTimerRef.current);
      }
      shareResetTimerRef.current = window.setTimeout(() => {
        setShareState('idle');
        shareResetTimerRef.current = null;
      }, 2000);
      onMenuClose();
    } catch (err) {
      console.error('Share failed:', err);
      toast('Could not share trip', { type: 'error' });
      setShareState('idle');
    }
  }, [hasDayCards, shareState, toast, onMenuClose]);

  const handleLogin = useCallback(async () => {
    try {
      await login();
    } catch (err) {
      console.error('Login failed:', err);
    }
  }, [login]);

  const handleLogout = useCallback(async () => {
    try {
      await logout();
      onMenuClose();
    } catch (err) {
      console.error('Logout failed:', err);
    }
  }, [logout, onMenuClose]);

  return useMemo(() => ({
    pdfState,
    shareState,
    handleNewTrip,
    handlePdfExport,
    handleShareTrip,
    handleLogin,
    handleLogout,
  }), [pdfState, shareState, handleNewTrip, handlePdfExport, handleShareTrip, handleLogin, handleLogout]);
}
