'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * TileDetailsModal
 *
 * Full evaluation modal for S2 (Plan) discovery.
 * Shows all details needed to evaluate and compare options:
 * - Image carousel
 * - Rating, location, amenities
 * - Price breakdown
 * - Save to shortlist action
 *
 * Note: No "View deal" button in S2. Booking links unlock in S3.
 */
import {
  X,
} from 'lucide-react';
import { memo, useCallback, useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';

import { TileDetailsInfo } from '@/components/tiles/TileDetailsInfo';
import { ModalErrorBoundary } from '@/components/ui/ModalErrorBoundary';
import { formatTilePriceDetailed } from '@/lib/format-utils';
import { isFlightType } from '@/lib/utils';
import type { ViewMode } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { PartnerPrice, Tile } from '@/types/tile';

import {
  getTileAIReasoning,
  getTileAmenities,
  getTileCancellationText,
  getTileCheckTimes,
  getTileImages,
  getTileReviewCount,
  isTileAIPick,
} from './tileHelpers';
import { TileDetailsFooter, TileDetailsImageCarousel } from './tileSections';

interface TileDetailsModalProps {
  tile: Tile | null;
  isOpen: boolean;
  isSaved?: boolean;
  /** Whether booking links are unlocked (S3) */
  isBookingUnlocked?: boolean;
  onClose: () => void;
  onSaveClick?: (tile: Tile) => void;
  /** Callback to open a sheet (for "Set trip dates" CTA) */
  onOpenSheet?: (sheet: SheetType) => void;
  /** Current mode for mode-specific sections */
  mode?: ViewMode;
  /** Partner prices for BOOKING mode price comparison */
  partnerPrices?: PartnerPrice[];
  /** Callback when user books from a partner */
  onBook?: (tile: Tile, partner: string) => void;
}

export const TileDetailsModal = memo(function TileDetailsModal({
  tile,
  isOpen,
  isSaved = false,
  isBookingUnlocked = false,
  onClose,
  onSaveClick,
  onOpenSheet,
  mode = 'planning',
  partnerPrices,
  onBook,
}: TileDetailsModalProps) {
  // Close on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  // Prevent body scroll when modal is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [isOpen]);

  const images = useMemo(() => (tile ? getTileImages(tile) : []), [tile]);
  const amenities = useMemo(() => (tile ? getTileAmenities(tile) : []), [tile]);
  const checkTimes = useMemo(() => (tile ? getTileCheckTimes(tile) : {}), [tile]);
  const cancellationText = useMemo(
    () => (tile ? getTileCancellationText(tile) : null),
    [tile]
  );
  const priceDisplay = useMemo(
    () => (tile ? formatTilePriceDetailed(tile) : { perUnit: '' }),
    [tile]
  );
  const reviewCount = useMemo(() => (tile ? getTileReviewCount(tile) : null), [tile]);
  const aiReasoning = useMemo(() => (tile ? getTileAIReasoning(tile) : null), [tile]);
  const aiPick = useMemo(() => (tile ? isTileAIPick(tile) : false), [tile]);

  const handleSaveClick = useCallback(() => {
    if (tile && onSaveClick) {
      onSaveClick(tile);
    }
  }, [tile, onSaveClick]);

  if (!isOpen || !tile) return null;

  const isFlight = isFlightType(tile.type || '');

  // Use portal to render at document root, escaping stacking contexts
  return createPortal(
    <ModalErrorBoundary>
    <div className="fixed inset-0 z-[1200] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative z-10 max-h-[90vh] w-full max-w-lg overflow-hidden rounded-xl bg-white dark:bg-zinc-900 shadow-card">
        {/* Header with close button */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-zinc-200 dark:border-white/10 bg-white dark:bg-zinc-900 px-4 py-3">
          <h2 className="line-clamp-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
            {tile.title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-full p-1.5 text-zinc-500 dark:text-zinc-400 transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-200"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Scrollable content */}
        <div className="max-h-[calc(90vh-64px-80px)] overflow-y-auto">
          {/* Image carousel */}
          <TileDetailsImageCarousel images={images} title={tile.title} />

          {/* Content */}
          <TileDetailsInfo
            tile={tile}
            isFlight={isFlight}
            mode={mode}
            reviewCount={reviewCount}
            checkTimes={checkTimes}
            cancellationText={cancellationText}
            priceDisplay={priceDisplay}
            amenities={amenities}
            aiReasoning={aiReasoning}
            aiPick={aiPick}
            partnerPrices={partnerPrices}
            onBook={onBook}
          />
        </div>

        <TileDetailsFooter
          tile={tile}
          isSaved={isSaved}
          isBookingUnlocked={isBookingUnlocked}
          onSaveClick={handleSaveClick}
          onClose={onClose}
          onOpenSheet={onOpenSheet}
        />
      </div>
    </div>
    </ModalErrorBoundary>,
    document.body
  );
});

export default TileDetailsModal;
