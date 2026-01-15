'use client';

import { Info } from 'lucide-react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

/**
 * Required legal text for Expedia Rapid API price display.
 * This exact text must be shown when displaying taxes and fees.
 */
const EXPEDIA_TAX_LEGAL_TEXT =
  'The taxes are tax recovery charges paid to vendors (e.g. hotels); ' +
  'for details, please see our Terms of Use. Service fees are retained ' +
  'as compensation in servicing your booking and may include fees charged by vendors.';

type TaxesFeesTooltipProps = {
  taxAndServiceFee?: number;
  propertyFee?: number;
  currency?: string;
};

/**
 * Displays "Incl. taxes & fees" with an info icon that shows
 * the required Expedia legal text when clicked/hovered.
 *
 * Required for Expedia Rapid API compliance.
 */
export function TaxesFeesTooltip({
  taxAndServiceFee,
  propertyFee,
  currency = '',
}: TaxesFeesTooltipProps) {
  const totalFees = (taxAndServiceFee ?? 0) + (propertyFee ?? 0);

  // Don't render if no fees data available
  if (!totalFees && taxAndServiceFee === undefined && propertyFee === undefined) {
    return null;
  }

  const feesText = totalFees
    ? `Incl. ${Math.round(totalFees).toLocaleString()} ${currency} taxes & fees`
    : 'Incl. taxes & fees';

  return (
    <div className="flex items-center gap-1 text-xs text-muted-foreground">
      <span>{feesText}</span>
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="inline-flex items-center justify-center rounded-full hover:bg-muted/50 p-0.5 transition-colors"
            aria-label="Tax and fee information"
          >
            <Info className="h-3 w-3" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="max-w-xs text-xs p-3" side="top" align="start">
          <p className="text-muted-foreground leading-relaxed">{EXPEDIA_TAX_LEGAL_TEXT}</p>
        </PopoverContent>
      </Popover>
    </div>
  );
}
