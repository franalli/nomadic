'use client';

/* eslint no-unused-vars: ["error", { "args": "none" }] */
/**
 * ActivityMiniCard
 *
 * Rich activity card with thumbnail, duration, specialist badge,
 * and booking/context menu actions.
 *
 * @see docs/ux_unified_architecture.md Section 10.C
 */

import { CheckCircle, Clock, MoreVertical, RefreshCw, Sparkles, Star, Trash2 } from 'lucide-react';
import Image from 'next/image';
import { useEffect, useMemo, useState } from 'react';

import { getTopicLabel } from '@/components/plan/stages/StrategyHeroUtils';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { DS } from '@/lib/design-system';
import {
  getSignedGooglePlacesPhotoProxyUrl,
  isGooglePlacesPhotoProxyUrl,
  normalizeGooglePlacesPhotoName,
} from '@/lib/googlePlacesPhoto';
import { placeholderImageForTile } from '@/lib/placeholders';
import { cn, normalizeTitle } from '@/lib/utils';
import type { DayBlock } from '@/types/plan-envelope';

import { HoldToDeleteButton } from './HoldToDeleteButton';
import { PreferenceAttributionBadge, type PreferenceStatus } from './PreferenceAttributionBadge';
import type { DisplayTime } from './types';

// Tailwind class lookups keyed by specialist type (Tailwind JIT needs static strings)
const BG_COLOR_CLASS: Record<string, string> = {
  browse: 'bg-amber-100 dark:bg-amber-900/30',
  diving: 'bg-cyan-100 dark:bg-cyan-900/30',
  hiking: 'bg-emerald-100 dark:bg-emerald-900/30',
  skiing: 'bg-blue-100 dark:bg-blue-900/30',
  cycling: 'bg-lime-100 dark:bg-lime-900/30',
  surfing: 'bg-indigo-100 dark:bg-indigo-900/30',
  boating: 'bg-cyan-100 dark:bg-cyan-900/30',
  sailing: 'bg-cyan-100 dark:bg-cyan-900/30',
  climbing: 'bg-orange-100 dark:bg-orange-900/30',
  wildlife_safari: 'bg-amber-100 dark:bg-amber-900/30',
  yoga: 'bg-purple-100 dark:bg-purple-900/30',
  wellness: 'bg-violet-100 dark:bg-violet-900/30',
  spa: 'bg-violet-100 dark:bg-violet-900/30',
  nightlife: 'bg-fuchsia-100 dark:bg-fuchsia-900/30',
  cooking: 'bg-pink-100 dark:bg-pink-900/30',
  food: 'bg-red-100 dark:bg-red-900/30',
  culture: 'bg-rose-100 dark:bg-rose-900/30',
  cultural: 'bg-rose-100 dark:bg-rose-900/30',
  temples: 'bg-rose-100 dark:bg-rose-900/30',
  sightseeing: 'bg-sky-100 dark:bg-sky-900/30',
  photography: 'bg-sky-100 dark:bg-sky-900/30',
  beach: 'bg-emerald-100 dark:bg-emerald-900/30',
  shopping: 'bg-pink-100 dark:bg-pink-900/30',
  relaxation: 'bg-yellow-100 dark:bg-yellow-900/30',
  tours: 'bg-blue-100 dark:bg-blue-900/30',
  nature: 'bg-green-100 dark:bg-green-900/30',
  adventure: 'bg-orange-100 dark:bg-orange-900/30',
};

const ICON_COLOR_CLASS: Record<string, string> = {
  browse: 'text-amber-600',
  diving: 'text-cyan-500',
  hiking: 'text-emerald-500',
  skiing: 'text-blue-500',
  cycling: 'text-lime-500',
  surfing: 'text-indigo-500',
  boating: 'text-cyan-500',
  sailing: 'text-cyan-500',
  climbing: 'text-orange-500',
  wildlife_safari: 'text-amber-500',
  yoga: 'text-purple-500',
  wellness: 'text-violet-500',
  spa: 'text-violet-500',
  nightlife: 'text-fuchsia-500',
  cooking: 'text-pink-500',
  food: 'text-red-500',
  culture: 'text-rose-500',
  cultural: 'text-rose-500',
  temples: 'text-rose-500',
  sightseeing: 'text-sky-500',
  photography: 'text-sky-500',
  beach: 'text-emerald-500',
  shopping: 'text-pink-500',
  relaxation: 'text-yellow-500',
  tours: 'text-blue-500',
  nature: 'text-green-500',
  adventure: 'text-orange-500',
};

const BADGE_BG_CLASS: Record<string, string> = {
  browse: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  diving: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  hiking: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
  skiing: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  cycling: 'bg-lime-100 dark:bg-lime-900/30 text-lime-700 dark:text-lime-400',
  surfing: 'bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400',
  boating: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  sailing: 'bg-cyan-100 dark:bg-cyan-900/30 text-cyan-700 dark:text-cyan-400',
  climbing: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400',
  wildlife_safari: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400',
  yoga: 'bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400',
  wellness: 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400',
  spa: 'bg-violet-100 dark:bg-violet-900/30 text-violet-700 dark:text-violet-400',
  nightlife: 'bg-fuchsia-100 dark:bg-fuchsia-900/30 text-fuchsia-700 dark:text-fuchsia-400',
  cooking: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-400',
  food: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400',
  culture: 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400',
  cultural: 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400',
  temples: 'bg-rose-100 dark:bg-rose-900/30 text-rose-700 dark:text-rose-400',
  sightseeing: 'bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400',
  photography: 'bg-sky-100 dark:bg-sky-900/30 text-sky-700 dark:text-sky-400',
  beach: 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400',
  shopping: 'bg-pink-100 dark:bg-pink-900/30 text-pink-700 dark:text-pink-400',
  relaxation: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400',
  tours: 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400',
  nature: 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
  adventure: 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400',
};

const PRICE_LEVEL_LABEL: Record<number, string> = {
  0: 'Free',
  1: '$',
  2: '$$',
  3: '$$$',
  4: '$$$$',
};

function toPriceLevelLabel(value: unknown): string | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return PRICE_LEVEL_LABEL[value];
  }
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  if (!trimmed) return undefined;
  return ['Free', '$', '$$', '$$$', '$$$$'].includes(trimmed) ? trimmed : undefined;
}

function parsePriceEstimate(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return value;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const numericMatch = trimmed.match(/(\d+(?:\.\d+)?)/);
    const numeric = numericMatch ? Number(numericMatch[1]) : Number.NaN;
    if (Number.isFinite(numeric) && numeric > 0) return numeric;
  }
  return null;
}

function resolvePriceLevelLabel(block: DayBlock): string | undefined {
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? bookedTile.meta as Record<string, unknown>
    : null;

  return (
    toPriceLevelLabel(block.price_level)
    ?? toPriceLevelLabel(bookedTile?.price_level)
    ?? toPriceLevelLabel(meta?.price_level)
    ?? toPriceLevelLabel(block.price_estimate)
    ?? toPriceLevelLabel(bookedTile?.price_estimate)
    ?? toPriceLevelLabel(meta?.price_estimate)
  );
}

function resolvePriceEstimate(block: DayBlock): number | null {
  const fromBlock = parsePriceEstimate(block.price_estimate);
  if (fromBlock != null) return fromBlock;

  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const fromBookedTile = parsePriceEstimate(bookedTile?.price_estimate);
  if (fromBookedTile != null) return fromBookedTile;

  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? bookedTile.meta as Record<string, unknown>
    : null;
  return parsePriceEstimate(meta?.price_estimate);
}

function formatDurationValue(hours: number): string {
  const rounded = Math.round(hours * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)}h`;
}

function normalizeDurationLabel(value: unknown): string | undefined {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return formatDurationValue(value);
  }
  if (typeof value !== 'string') return undefined;

  const trimmed = value.trim();
  if (!trimmed) return undefined;
  const lower = trimmed.toLowerCase();

  const hoursMatch = lower.match(/(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours)\b/);
  if (hoursMatch) {
    return formatDurationValue(Number(hoursMatch[1]));
  }

  const minutesMatch = lower.match(/(\d+(?:\.\d+)?)\s*(m|min|mins|minute|minutes)\b/);
  if (minutesMatch) {
    return formatDurationValue(Number(minutesMatch[1]) / 60);
  }

  return trimmed;
}

function resolveDurationLabel(block: DayBlock): string | undefined {
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? bookedTile.meta as Record<string, unknown>
    : null;

  return (
    normalizeDurationLabel(block.duration)
    ?? normalizeDurationLabel(bookedTile?.duration)
    ?? normalizeDurationLabel(meta?.duration)
    ?? normalizeDurationLabel(meta?.duration_hours)
  );
}

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

const borderAccentClass: Record<string, string> = {
  browse: 'border-l-amber-500',
  diving: 'border-l-cyan-500',
  hiking: 'border-l-emerald-500',
  skiing: 'border-l-blue-500',
  cycling: 'border-l-lime-500',
  surfing: 'border-l-indigo-500',
  boating: 'border-l-cyan-500',
  sailing: 'border-l-cyan-500',
  climbing: 'border-l-orange-500',
  wildlife_safari: 'border-l-amber-500',
  yoga: 'border-l-purple-500',
  wellness: 'border-l-violet-500',
  spa: 'border-l-violet-500',
  nightlife: 'border-l-fuchsia-500',
  cooking: 'border-l-pink-500',
  food: 'border-l-red-500',
  culture: 'border-l-rose-500',
  cultural: 'border-l-rose-500',
  temples: 'border-l-rose-500',
  sightseeing: 'border-l-sky-500',
  photography: 'border-l-sky-500',
  beach: 'border-l-emerald-500',
  shopping: 'border-l-pink-500',
  relaxation: 'border-l-yellow-500',
  tours: 'border-l-blue-500',
  nature: 'border-l-green-500',
  adventure: 'border-l-orange-500',
};

const CATEGORY_LABEL: Record<string, string> = {
  cultural: 'Cultural',
  tours: 'Tours',
  food: 'Food',
  nature: 'Nature',
  spa: 'Spa',
  adventure: 'Adventure',
};

const CATEGORY_ALIAS: Record<string, string> = {
  culture: 'cultural',
  tours: 'tours',
  attraction: 'tours',
  tourist_attraction: 'tours',
  point_of_interest: 'tours',
  travel_agency: 'tours',
  cultural_attraction: 'cultural',
  museum: 'cultural',
  art_gallery: 'cultural',
  historical_landmark: 'cultural',
  cultural_landmark: 'cultural',
  monument: 'cultural',
  plaza: 'cultural',
  ruins: 'cultural',
  fountain: 'cultural',
  hindu_temple: 'temples',
  temple: 'temples',
  church: 'cultural',
  place_of_worship: 'cultural',
  synagogue: 'cultural',
  mosque: 'cultural',
  restaurant: 'food',
  cafe: 'food',
  bar: 'food',
  bakery: 'food',
  meal_takeaway: 'food',
  meal_delivery: 'food',
  park: 'nature',
  natural_feature: 'nature',
  national_park: 'nature',
  campground: 'nature',
  zoo: 'nature',
  botanical_garden: 'nature',
  shopping_mall: 'shopping',
  market: 'shopping',
  store: 'shopping',
  clothing_store: 'shopping',
  department_store: 'shopping',
  beauty_salon: 'spa',
  gym: 'spa',
};

function toCategoryKey(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().toLowerCase();
  return normalized || null;
}

function canonicalCategoryKey(value: unknown): string | null {
  const key = toCategoryKey(value);
  if (!key) return null;
  const mapped = CATEGORY_ALIAS[key] ?? key;
  if (mapped in BG_COLOR_CLASS) return mapped;
  if (/(culture|cultural|heritage)/.test(key)) return 'cultural';
  if (/(museum|landmark|historic|monument|plaza|fountain)/.test(key)) return 'cultural';
  if (/(temple|church|worship|mosque|synagogue)/.test(key)) return 'temples';
  if (/(restaurant|cafe|bar|bakery|food|meal)/.test(key)) return 'food';
  if (/(park|garden|nature|zoo|camp)/.test(key)) return 'nature';
  if (/(shop|store|market|mall)/.test(key)) return 'shopping';
  if (/(spa|wellness|gym|beauty)/.test(key)) return 'spa';
  if (/(tour|point_of_interest|visitor|travel_agency)/.test(key)) return 'tours';
  return null;
}

function resolveActivityCategory(block: DayBlock): { key: string; label: string } | null {
  const bookedTile = block.booked_tile as Record<string, unknown> | undefined;
  const meta = bookedTile?.meta && typeof bookedTile.meta === 'object'
    ? bookedTile.meta as Record<string, unknown>
    : undefined;
  const key =
    canonicalCategoryKey(block.map_type) ??
    canonicalCategoryKey(block.specialist_type) ??
    canonicalCategoryKey(bookedTile?.map_type) ??
    canonicalCategoryKey(meta?.map_type) ??
    canonicalCategoryKey((bookedTile as Record<string, unknown> | undefined)?.browse_category) ??
    canonicalCategoryKey(bookedTile?.category) ??
    canonicalCategoryKey(meta?.category);
  if (!key) return null;

  const baseLabel = CATEGORY_LABEL[key] ?? getTopicLabel(key);
  return {
    key,
    label: baseLabel,
  };
}

interface ActivityMiniCardProps {
  block: DayBlock;
  displayTime?: DisplayTime;
  onBook?: () => void;
  onUnassign?: () => void;
  isBooked?: boolean;
  /** Current view mode - controls Book button visibility */
  mode?: 'planning' | 'booking';
  /** Preference status for attribution badge */
  preferenceStatus?: PreferenceStatus;
  /** Alternative tile ID when AI overrode user preference */
  alternativeTileId?: string;
  /** Callback to switch to alternative tile */
  onSwitchToAlternative?: (tileId: string) => void;
  /** Callback when user completes hold-to-delete */
  onRemove?: () => void;
  /** Whether this block can be removed (not locked/buffer) */
  isRemovable?: boolean;
  /** Whether this block is map-highlighted (hovered on map) */
  isHighlighted?: boolean;
}

export function ActivityMiniCard({
  block,
  displayTime,
  onBook,
  onUnassign,
  isBooked,
  mode = 'planning',
  preferenceStatus,
  alternativeTileId,
  onSwitchToAlternative,
  onRemove,
  isRemovable,
  isHighlighted,
}: ActivityMiniCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [imageErrored, setImageErrored] = useState(false);
  const [signedGooglePhotoUrl, setSignedGooglePhotoUrl] = useState<string | undefined>(undefined);
  const activityCategory = resolveActivityCategory(block);
  const st = activityCategory?.key ?? '';
  const categoryLabel = activityCategory?.label;
  const isUnschedulable = block.unschedulable === true;

  const bg = BG_COLOR_CLASS[st] || 'bg-zinc-100 dark:bg-zinc-800/50';
  const iconColor = ICON_COLOR_CLASS[st] || 'text-zinc-500';
  const badgeBg = BADGE_BG_CLASS[st] || 'bg-zinc-100 dark:bg-zinc-800/50 text-zinc-700 dark:text-zinc-400';
  const activityBorderClass = isUnschedulable
    ? 'border-l-amber-500'
    : borderAccentClass[st] || 'border-l-zinc-300 dark:border-l-zinc-600';
  const priceLevelLabel = resolvePriceLevelLabel(block);
  const resolvedPriceEstimate = resolvePriceEstimate(block);
  const resolvedDuration = resolveDurationLabel(block);
  const showEstimatedPrice = !priceLevelLabel && resolvedPriceEstimate != null;
  const rawActivityTitle = block.activity_type || '';
  const normalizedActivityTitle = normalizeTitle(rawActivityTitle);
  const summaryTitle = (block.summary || '').trim();
  const activityTitleHasUppercase = /[A-Z]/.test(rawActivityTitle);
  const resolvedTitle = isUnschedulable
    ? summaryTitle
    : (!activityTitleHasUppercase && summaryTitle
      ? summaryTitle
      : (normalizedActivityTitle || summaryTitle));
  const showIntensityBadge = block.intensity && !block.is_buffer && block.specialist_type !== 'local_expert' && (() => {
    const activityLower = (block.activity_type || '').toLowerCase();
    const summaryLower = (block.summary || '').toLowerCase();
    return !['free', 'rest', 'leisure', 'explore', 'relax', 'recovery'].some(
      keyword => activityLower.includes(keyword) || summaryLower.includes(keyword)
    );
  })();
  const hasContextBadges = Boolean(
    displayTime
    || categoryLabel
    || showIntensityBadge
  );
  const photoName = useMemo(() => resolveActivityPhotoName(block), [block]);
  const primaryImageUrl = useMemo(
    () => resolveActivityImageUrl(block, signedGooglePhotoUrl),
    [block, signedGooglePhotoUrl]
  );
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

  const activeConstraints = block.active_constraints ?? [];
  const severityWeight: Record<string, number> = {
    blocking: 4,
    warning: 3,
    info: 2,
    success: 1,
  };
  const mergedConstraintSeverity = activeConstraints.reduce<'blocking' | 'warning' | 'info' | 'success'>(
    (current, next) => {
      const nextSeverity = next.severity in severityWeight ? next.severity : 'info';
      return severityWeight[nextSeverity] > severityWeight[current] ? nextSeverity : current;
    },
    'info'
  );
  const mergedConstraintIcons = Array.from(
    new Set(activeConstraints.map(c => c.icon).filter(Boolean))
  ).join(' ');
  const mergedConstraintTitles = Array.from(
    new Set(activeConstraints.map(c => c.title).filter(Boolean))
  ).join(' · ');
  const mergedConstraintDescription = Array.from(
    new Set(activeConstraints.map(c => c.description).filter(Boolean))
  ).join(' · ');

  return (
    <div className="flex flex-col gap-1.5">
    <div
      className={cn(
        'group relative flex flex-col lg:flex-row gap-3 p-3 rounded-xl border border-l-4 transition-colors duration-150',
        isUnschedulable
          ? 'bg-amber-50/50 dark:bg-amber-900/10 border-amber-200 dark:border-amber-800/40'
          : isHighlighted
            ? 'bg-zinc-700/70 border-emerald-500/40 shadow-lg shadow-emerald-500/10'
            : 'bg-white dark:bg-zinc-800/50 hover:shadow-soft',
        activityBorderClass,
      )}
    >

      {/* Thumbnail */}
      <div className="w-full lg:w-20 shrink-0">
        {/* Thumbnail — full-width banner on mobile, inline 80×80 on desktop */}
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
          <div className={cn('w-full h-32 lg:w-20 lg:h-20 rounded-lg flex items-center justify-center', bg)}>
            <Sparkles className={cn('w-8 h-8', iconColor)} />
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <h4 className="font-semibold text-sm line-clamp-2 text-zinc-900 dark:text-white">
          {resolvedTitle}
        </h4>

        {(block.rating != null || priceLevelLabel || showEstimatedPrice || resolvedDuration) && (
          <div className="mt-1 flex items-center gap-2 flex-wrap">
            {block.rating != null && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-0.5">
                <Star className="w-3 h-3 fill-current text-amber-400" />
                {block.rating.toFixed(1)}
                {block.review_count != null && (
                  <span className="ml-0.5">
                    ({block.review_count >= 1000
                      ? `${Math.round(block.review_count / 1000)}K`
                      : block.review_count.toLocaleString()})
                  </span>
                )}
              </span>
            )}

            {priceLevelLabel && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                {priceLevelLabel}
              </span>
            )}

            {showEstimatedPrice && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400">
                ~${Math.round(resolvedPriceEstimate).toLocaleString()}
              </span>
            )}

            {resolvedDuration && (
              <span className="text-xs text-zinc-500 dark:text-zinc-400 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {resolvedDuration}
              </span>
            )}
          </div>
        )}

        {hasContextBadges && (
          <div className="mt-1 flex items-center gap-1.5 flex-wrap min-w-0">
            {categoryLabel && (
              <span className={cn('w-fit text-xs px-2 py-0.5 rounded font-medium uppercase', badgeBg)}>
                {categoryLabel.toUpperCase()}
              </span>
            )}

            {displayTime && (
              displayTime.type === 'exact' ? (
                <span className="text-xs font-mono text-zinc-500 dark:text-zinc-400">
                  {displayTime.value}
                </span>
              ) : (
                <span className={cn(DS.textSize.micro, 'px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 uppercase tracking-wide')}>
                  {displayTime.value}
                </span>
              )
            )}

            {showIntensityBadge && (
              <span className={cn(
                DS.textSize.micro, 'px-1.5 py-0.5 rounded-full font-semibold uppercase tracking-wide border',
                block.intensity === 'light' && 'bg-green-500/20 text-green-600 dark:text-green-400 border-green-500/30',
                block.intensity === 'moderate' && 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border-amber-500/30',
                block.intensity === 'challenging' && 'bg-red-500/20 text-red-600 dark:text-red-400 border-red-500/30'
              )}>
                {block.intensity === 'light' ? 'easy' : block.intensity}
              </span>
            )}
          </div>
        )}

        {/* Description - show summary if different from title (skip for unschedulable, summary IS title) */}
        {!isUnschedulable && block.summary && block.summary !== resolvedTitle && (
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 line-clamp-1">
            {block.summary}
          </p>
        )}

        {/* Unschedulable constraint chip — solution-first messaging */}
        {isUnschedulable && block.unschedulable_reason && (
          <div className="flex items-start gap-2 mt-2 p-2.5 rounded-lg text-xs bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40">
            <Clock className="w-3.5 h-3.5 text-amber-500 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-amber-700 dark:text-amber-400">
                {block.unschedulable_days_needed
                  ? `Extend trip by ${block.unschedulable_days_needed} day${block.unschedulable_days_needed > 1 ? 's' : ''} to unlock`
                  : 'Extend trip to unlock'}
              </div>
              <div className="text-zinc-600 dark:text-zinc-400 mt-0.5">
                {block.unschedulable_reason}
              </div>
            </div>
          </div>
        )}

        {/* Preference Attribution Badge */}
        {preferenceStatus && (
          <PreferenceAttributionBadge
            status={preferenceStatus}
            alternativeTileId={alternativeTileId}
            onSwitchToAlternative={onSwitchToAlternative}
            className="mt-2"
          />
        )}
      </div>

      {/* Action Button (Book) - only show in booking mode when not booked */}
      {mode === 'booking' && !isBooked && onBook && (
        <button
          onClick={onBook}
          className={cn(DS.actions.primary, 'self-center px-3 py-1.5 text-xs font-semibold rounded-lg shrink-0')}
        >
          Book
        </button>
      )}

      {/* Booked indicator */}
      {isBooked && !onUnassign && (
        <div className="self-center">
          <CheckCircle className="w-5 h-5 text-emerald-500" />
        </div>
      )}

      {/* Context Menu (visible on hover when booked) */}
      {isBooked && onUnassign && (
        <Popover open={menuOpen} onOpenChange={setMenuOpen}>
          <PopoverTrigger asChild>
            <button aria-label="More options" className="absolute top-2 right-2 p-1.5 rounded-lg opacity-0 group-hover:opacity-100 hover:bg-zinc-100 dark:hover:bg-white/10 transition-opacity">
              <MoreVertical className="w-4 h-4 text-zinc-500 dark:text-zinc-400" />
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-48 p-1">
            {onBook && (
              <button
                onClick={() => {
                  setMenuOpen(false);
                  onBook();
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-white/10 transition-colors"
              >
                <RefreshCw className="w-4 h-4" />
                Change Selection
              </button>
            )}
            <button
              onClick={() => {
                setMenuOpen(false);
                onUnassign();
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
            >
              <Trash2 className="w-4 h-4" />
              Remove from Itinerary
            </button>
          </PopoverContent>
        </Popover>
      )}

      {/* Hold-to-delete — only for removable, non-booked blocks */}
      {isRemovable && onRemove && !(isBooked && onUnassign) && (
        <div className="absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <HoldToDeleteButton onDelete={onRemove} />
        </div>
      )}
    </div>
    {/* Constraint sub-cards — always below the activity card */}
    {activeConstraints.length > 0 && (() => {
      return (
        <div className="pl-1">
          <div
            className={cn(
              'flex items-start gap-2 p-2.5 rounded-lg text-xs',
              mergedConstraintSeverity === 'warning' && 'bg-amber-50 dark:bg-amber-900/10 border border-amber-200 dark:border-amber-800/40',
              mergedConstraintSeverity === 'info' && 'bg-blue-50 dark:bg-blue-900/10 border border-blue-200 dark:border-blue-800/40',
              mergedConstraintSeverity === 'success' && 'bg-emerald-50 dark:bg-emerald-900/10 border border-emerald-200 dark:border-emerald-800/40',
              mergedConstraintSeverity === 'blocking' && 'bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800/40'
            )}
          >
            <span className="flex-shrink-0 leading-none">
              {mergedConstraintIcons}
            </span>
            <div className="flex-1 min-w-0">
              <div className={cn(
                'font-semibold mb-0.5',
                mergedConstraintSeverity === 'warning' && 'text-amber-700 dark:text-amber-400',
                mergedConstraintSeverity === 'info' && 'text-blue-700 dark:text-blue-400',
                mergedConstraintSeverity === 'success' && 'text-emerald-700 dark:text-emerald-400',
                mergedConstraintSeverity === 'blocking' && 'text-red-700 dark:text-red-400'
              )}>
                {mergedConstraintTitles}
              </div>
              <div className="text-zinc-600 dark:text-zinc-400">
                {mergedConstraintDescription}
              </div>
            </div>
          </div>
        </div>
      );
    })()}
    </div>
  );
}
