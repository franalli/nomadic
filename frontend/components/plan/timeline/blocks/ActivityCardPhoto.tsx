'use client';

/**
 * ActivityCardPhoto
 *
 * Photo/image section for ActivityMiniCard.
 * Handles Google Places photo signing, image URL resolution,
 * fallback placeholders, and thumbnail rendering.
 */

import { Sparkles } from 'lucide-react';
import Image from 'next/image';
import { useEffect, useMemo, useState } from 'react';

import {
  getSignedGooglePlacesPhotoProxyUrl,
  isGooglePlacesPhotoProxyUrl,
  normalizeGooglePlacesPhotoName,
} from '@/lib/googlePlacesPhoto';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

// ---------------------------------------------------------------------------
// Image resolution helpers
// ---------------------------------------------------------------------------

function normalizeImageCandidate(url: unknown): string | undefined {
  if (typeof url !== 'string') return undefined;
  const trimmed = url.trim();
  if (!trimmed) return undefined;
  if (trimmed.startsWith('//')) return `https:${trimmed}`;
  return trimmed;
}

function isAllowedImageUrl(url: string | undefined): boolean {
  if (!url) return false;
  if (isGooglePlacesPhotoProxyUrl(url)) return true;
  if (url.startsWith('/')) return true;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') return false;
    const host = parsed.hostname.toLowerCase();
    return host === 'images.unsplash.com'
      || host === 'plus.unsplash.com'
      || host.endsWith('.unsplash.com')
      || host === 'pics.avs.io'
      || host === 'places.googleapis.com';
  } catch {
    return false;
  }
}

function resolveActivityPhotoName(block: DayBlock): string | undefined {
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? bookedTile.meta as Record<string, unknown>
    : undefined;
  return normalizeGooglePlacesPhotoName(meta?.photo_name)
    ?? normalizeGooglePlacesPhotoName(bookedTile?.photo_name);
}

function resolveActivityImageUrl(block: DayBlock, signedGooglePhotoUrl?: string): string | undefined {
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? bookedTile.meta as Record<string, unknown>
    : undefined;
  const bookedTileImage = normalizeImageCandidate(bookedTile?.image_url);
  const metaImage = normalizeImageCandidate(meta?.image_url);
  const blockImage = normalizeImageCandidate(block.image_url);

  for (const candidate of [signedGooglePhotoUrl, blockImage, bookedTileImage, metaImage]) {
    if (isAllowedImageUrl(candidate)) return candidate;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export interface ActivityCardPhotoProps {
  block: DayBlock;
  /** Specialist-based background color class for the fallback icon area */
  bgClass: string;
  /** Specialist-based icon color class */
  iconColorClass: string;
  /** Resolved title used for fallback image seed */
  resolvedTitle: string;
}

export function ActivityCardPhoto({
  block,
  bgClass,
  iconColorClass,
  resolvedTitle,
}: ActivityCardPhotoProps) {
  const [imageErrored, setImageErrored] = useState(false);
  const [signedGooglePhotoUrl, setSignedGooglePhotoUrl] = useState<string | undefined>(undefined);

  const photoName = useMemo(() => resolveActivityPhotoName(block), [block]);

  const primaryImageUrl = useMemo(
    () => resolveActivityImageUrl(block, signedGooglePhotoUrl),
    [block, signedGooglePhotoUrl]
  );

  const summaryTitle = (block.summary || '').trim();

  const fallbackImageUrl = useMemo(
    () => placeholderImageForTile({
      id: block.id || block.booked_tile?.id,
      type: 'activity',
      category: block.map_type || block.specialist_type || block.activity_type || 'activity',
      destination: summaryTitle || resolvedTitle || 'activity',
    }),
    [block.id, block.booked_tile?.id, block.map_type, block.specialist_type, block.activity_type, summaryTitle, resolvedTitle]
  );

  const cardImageUrl = imageErrored ? fallbackImageUrl : (primaryImageUrl || fallbackImageUrl);

  useEffect(() => {
    let isMounted = true;
    setSignedGooglePhotoUrl(undefined);
    if (!photoName) return () => {
      isMounted = false;
    };

    getSignedGooglePlacesPhotoProxyUrl(photoName, { maxWidth: 320, maxHeight: 240 })
      .then((url) => {
        if (!isMounted) return;
        setSignedGooglePhotoUrl(url);
      })
      .catch(() => {
        if (!isMounted) return;
        setSignedGooglePhotoUrl(undefined);
      });

    return () => {
      isMounted = false;
    };
  }, [photoName]);

  useEffect(() => {
    setImageErrored(false);
  }, [primaryImageUrl, block.id, block.booked_tile?.id]);

  return (
    <div className="w-full lg:w-20 shrink-0">
      {/* Thumbnail -- full-width banner on mobile, inline 80x80 on desktop */}
      {cardImageUrl ? (
        <div className="relative w-full h-32 lg:w-20 lg:h-20 rounded-lg overflow-hidden">
          <Image
            src={cardImageUrl}
            alt={block.summary}
            fill
            className="object-cover"
            sizes="(min-width: 1024px) 80px, 100vw"
            unoptimized={cardImageUrl.startsWith('/') || isGooglePlacesPhotoProxyUrl(cardImageUrl)}
            onError={() => {
              if (!imageErrored) {
                setImageErrored(true);
              }
            }}
          />
        </div>
      ) : (
        <div className={cn('w-full h-32 lg:w-20 lg:h-20 rounded-lg flex items-center justify-center', bgClass)}>
          <Sparkles className={cn('w-8 h-8', iconColorClass)} />
        </div>
      )}
    </div>
  );
}
