'use client';

import { Check, Download, Loader2 } from 'lucide-react';
import { useCallback, useState } from 'react';

import { useToast } from '@/components/ui/toast';
import { DS } from '@/lib/design-system';
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
  const { toast } = useToast();

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
      const message = err instanceof Error ? err.message : 'PDF export failed';
      toast(message, { type: 'error' });
      setState('idle');
    }
  }, [state, tripInputs, dayCards, tiles, toast]);

  if (dayCards.length === 0) return null;

  return (
    <button
      type="button"
      onClick={handleExport}
      disabled={state === 'loading'}
      className={cn(
        DS.textSize.micro,
        'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 font-bold uppercase tracking-widest',
        'text-muted-foreground hover:bg-accent hover:text-foreground',
        'disabled:pointer-events-none disabled:opacity-60',
        state === 'loading' && 'cursor-wait',
      )}
    >
      {state === 'idle' && (
        <>
          <Download className="h-3.5 w-3.5" />
          <span>PDF</span>
        </>
      )}
      {state === 'loading' && (
        <>
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          <span>Exporting</span>
        </>
      )}
      {state === 'success' && (
        <>
          <Check className="h-3.5 w-3.5 text-emerald-500" />
          <span>Done</span>
        </>
      )}
    </button>
  );
}
