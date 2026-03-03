'use client';

import { Check, Download, Loader2 } from 'lucide-react';
import { useCallback, useState } from 'react';

import { extractTripPdfData } from '@/lib/pdfData';
import { cn } from '@/lib/utils';
import type { DocumentTripInputs } from '@/types/document';
import type { DayCard } from '@/types/plan-envelope';
import type { Tile } from '@/types/tile';

type ExportState = 'idle' | 'loading' | 'success';

interface PdfExportButtonProps {
  tripInputs?: DocumentTripInputs;
  dayCards: DayCard[];
  tiles: Record<string, Tile>;
}

export function PdfExportButton({ tripInputs, dayCards, tiles }: PdfExportButtonProps) {
  const [state, setState] = useState<ExportState>('idle');

  const handleExport = useCallback(async () => {
    if (state === 'loading') return;
    setState('loading');

    try {
      const [{ pdf }, { saveAs }, { TripPdfDocument }] = await Promise.all([
        import('@react-pdf/renderer'),
        import('file-saver'),
        import('./pdf/TripPdfDocument'),
      ]);

      const data = extractTripPdfData(tripInputs, dayCards, tiles);

      const blob = await pdf(<TripPdfDocument data={data} />).toBlob();

      const dest = (data.destination || 'Trip').replace(/\s+/g, '-');
      const start = tripInputs?.start_date
        ? new Date(tripInputs.start_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).replace(' ', '')
        : '';
      const end = tripInputs?.end_date
        ? new Date(tripInputs.end_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).replace(' ', '')
        : '';
      const datePart = start && end ? `_${start}-${end}` : '';
      const filename = `${dest}${datePart}.pdf`;

      saveAs(blob, filename);
      setState('success');
      setTimeout(() => setState('idle'), 2000);
    } catch (err) {
      console.error('PDF export failed:', err);
      setState('idle');
    }
  }, [state, tripInputs, dayCards, tiles]);

  if (dayCards.length === 0) return null;

  return (
    <button
      onClick={handleExport}
      disabled={state === 'loading'}
      className={cn(
        'inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-sm whitespace-nowrap transition-colors',
        'border-emerald-500/25 hover:border-emerald-500/40',
        'bg-emerald-500/[0.06] hover:bg-emerald-500/[0.10]',
        'text-emerald-600 dark:text-emerald-400 hover:text-emerald-500 dark:hover:text-emerald-300',
        'font-medium',
        state === 'loading' && 'opacity-60 cursor-wait',
      )}
    >
      {state === 'idle' && (
        <>
          <Download className="w-3.5 h-3.5" />
          <span>PDF</span>
        </>
      )}
      {state === 'loading' && (
        <>
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>PDF</span>
        </>
      )}
      {state === 'success' && (
        <>
          <Check className="w-3.5 h-3.5" />
          <span>Done</span>
        </>
      )}
    </button>
  );
}
