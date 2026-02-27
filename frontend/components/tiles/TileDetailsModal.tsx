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
  ChevronLeft,
  ChevronRight,
  Heart,
  Lock,
  MapPin,
  X,
} from 'lucide-react';
import { memo, useCallback, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';

import { TileDetailsInfo } from '@/components/tiles/TileDetailsInfo';
import { ModalErrorBoundary } from '@/components/ui/ModalErrorBoundary';
import { formatTilePriceDetailed } from '@/lib/format-utils';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, isFlightType } from '@/lib/utils';
import type { ViewMode } from '@/types/plan-envelope';
import type { SheetType } from '@/types/sheets';
import type { PartnerPrice, Tile } from '@/types/tile';

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

/**
 * Get images from tile (fallback to Unsplash placeholder)
 */
function getImages(tile: Tile): string[] {
  const meta = tile.meta as Record<string, unknown> | undefined;

  // Check for images array in meta
  if (meta?.images && Array.isArray(meta.images)) {
    return meta.images as string[];
  }

  // Fallback to single image or Unsplash placeholder
  if (tile.image_url) {
    return [tile.image_url];
  }

  // Use deterministic Unsplash placeholder
  return [placeholderImageForTile(tile)];
}

/**
 * Get amenities from tile meta
 */
function getAmenities(tile: Tile): string[] {
  const meta = tile.meta as Record<string, unknown> | undefined;

  if (meta?.amenities && Array.isArray(meta.amenities)) {
    return meta.amenities as string[];
  }

  if (meta?.features && Array.isArray(meta.features)) {
    return meta.features as string[];
  }

  return [];
}

/**
 * Get check-in/out times
 */
function getCheckTimes(tile: Tile): { checkIn?: string; checkOut?: string } {
  const meta = tile.meta as Record<string, unknown> | undefined;

  return {
    checkIn: typeof meta?.check_in === 'string' ? meta.check_in : undefined,
    checkOut: typeof meta?.check_out === 'string' ? meta.check_out : undefined,
  };
}

/**
 * Get cancellation policy text
 */
function getCancellationText(tile: Tile): string | null {
  if (tile.is_refundable === true) {
    const meta = tile.meta as Record<string, unknown> | undefined;
    if (typeof meta?.cancellation_deadline === 'string') {
      return `Free cancellation until ${meta.cancellation_deadline}`;
    }
    return 'Free cancellation available';
  }
  if (tile.is_refundable === false) {
    return 'Non-refundable';
  }
  return null;
}

/**
 * Get review count from meta
 */
function getReviewCount(tile: Tile): number | null {
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (typeof meta?.review_count === 'number') return meta.review_count;
  if (typeof meta?.reviews === 'number') return meta.reviews;
  return null;
}

/**
 * Get AI reasoning for why this tile was suggested (PLANNING mode)
 */
function getAIReasoning(tile: Tile): string | null {
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (typeof meta?.reasoning === 'string') return meta.reasoning;
  if (typeof meta?.ai_reasoning === 'string') return meta.ai_reasoning;
  return null;
}

/**
 * Check if tile is an AI pick
 */
function isAIPick(tile: Tile): boolean {
  const meta = tile.meta as Record<string, unknown> | undefined;
  return meta?.is_ai_pick === true || meta?.ai_recommended === true;
}

/**
 * Image Carousel component
 */
function ImageCarousel({ images, title }: { images: string[]; title?: string }) {
  const [currentIndex, setCurrentIndex] = useState(0);

  const goToPrevious = useCallback(() => {
    setCurrentIndex((prev) => (prev === 0 ? images.length - 1 : prev - 1));
  }, [images.length]);

  const goToNext = useCallback(() => {
    setCurrentIndex((prev) => (prev === images.length - 1 ? 0 : prev + 1));
  }, [images.length]);

  if (images.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center bg-gradient-to-br from-zinc-200 to-zinc-300 dark:from-zinc-700 dark:to-zinc-800">
        <MapPin className="h-12 w-12 text-zinc-500 dark:text-zinc-500" />
      </div>
    );
  }

  return (
    <div className="relative h-64 overflow-hidden bg-zinc-100 dark:bg-zinc-800">
      <img
        src={images[currentIndex]}
        alt={title ?? ''}
        className="h-full w-full object-cover"
      />

      {/* Navigation arrows */}
      {images.length > 1 && (
        <>
          <button
            type="button"
            onClick={goToPrevious}
            aria-label="Previous image"
            className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-1.5 text-white transition-colors hover:bg-black/70"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button
            type="button"
            onClick={goToNext}
            aria-label="Next image"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-black/50 p-1.5 text-white transition-colors hover:bg-black/70"
          >
            <ChevronRight className="h-5 w-5" />
          </button>

          {/* Dots indicator */}
          <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 gap-1.5">
            {images.map((_, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => setCurrentIndex(idx)}
                aria-label={`Go to image ${idx + 1}`}
                className={cn(
                  'h-2 w-2 rounded-full transition-colors',
                  idx === currentIndex ? 'bg-white' : 'bg-white/50'
                )}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
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

  const images = useMemo(() => (tile ? getImages(tile) : []), [tile]);
  const amenities = useMemo(() => (tile ? getAmenities(tile) : []), [tile]);
  const checkTimes = useMemo(() => (tile ? getCheckTimes(tile) : {}), [tile]);
  const cancellationText = useMemo(
    () => (tile ? getCancellationText(tile) : null),
    [tile]
  );
  const priceDisplay = useMemo(
    () => (tile ? formatTilePriceDetailed(tile) : { perUnit: '' }),
    [tile]
  );
  const reviewCount = useMemo(() => (tile ? getReviewCount(tile) : null), [tile]);
  const aiReasoning = useMemo(() => (tile ? getAIReasoning(tile) : null), [tile]);
  const aiPick = useMemo(() => (tile ? isAIPick(tile) : false), [tile]);

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
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-4 py-3">
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
          <ImageCarousel images={images} title={tile.title} />

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

        {/* Sticky footer */}
        <div className="sticky bottom-0 border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleSaveClick}
              className={cn(
                'flex flex-1 items-center justify-center gap-2 rounded-lg py-2.5 font-medium transition-colors',
                isSaved
                  ? 'bg-emerald-500/20 text-emerald-400'
                  : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-700'
              )}
            >
              <Heart className={cn('h-4 w-4', isSaved && 'fill-emerald-400')} />
              {isSaved ? 'Saved to shortlist' : 'Add to shortlist'}
            </button>
          </div>

          {/* Booking unlock status */}
          {isBookingUnlocked ? (
            // S3: View deal button enabled
            tile?.deeplink_url && (
              <button
                type="button"
                onClick={() => window.open(tile.deeplink_url, '_blank', 'noopener,noreferrer')}
                className="mt-3 flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-500 py-2.5 font-medium text-white transition-colors hover:bg-emerald-600"
              >
                View deal
              </button>
            )
          ) : (
            // S2: Locked state with actionable CTA
            <div className="mt-3 space-y-2">
              <div className="flex items-center justify-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-500">
                <Lock className="h-3 w-3" />
                <span>Booking links are locked</span>
              </div>
              {onOpenSheet && (
                <button
                  type="button"
                  onClick={() => {
                    onOpenSheet('dates');
                    onClose();
                  }}
                  className="flex w-full items-center justify-center gap-2 rounded-lg border border-zinc-200 dark:border-white/10 bg-zinc-100 dark:bg-zinc-800 py-2 text-sm font-medium text-zinc-800 dark:text-zinc-200 transition-colors hover:bg-zinc-200 dark:hover:bg-zinc-700"
                >
                  Set trip dates to unlock
                </button>
              )}
              {!onOpenSheet && (
                <p className="text-center text-xs text-zinc-500 dark:text-zinc-500">
                  Set trip dates and create your itinerary to unlock booking links.
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
    </ModalErrorBoundary>,
    document.body
  );
});

export default TileDetailsModal;
