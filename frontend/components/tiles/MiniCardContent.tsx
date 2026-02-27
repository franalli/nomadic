'use client';

import { ChevronDown, Clock, Code2, Heart, Moon, Settings, Sun, Sunset } from 'lucide-react';
import type { MouseEvent } from 'react';
import { useCallback, useMemo, useState } from 'react';

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { DS } from '@/lib/design-system';
import { formatTilePrice } from '@/lib/format-utils';
import { placeholderImageForTile } from '@/lib/placeholders';
import { getDeepLinkParams } from '@/lib/tileUtils';
import { cn, isFlightType, isHotelType } from '@/lib/utils';
import type { Tile } from '@/types/tile';

/**
 * Amenity icon mapping for inline display (max 3 shown)
 */
const AMENITY_ICONS: Record<string, string> = {
  pool: '\u{1F3CA}',
  'swimming pool': '\u{1F3CA}',
  breakfast: '\u{1F373}',
  'breakfast included': '\u{1F373}',
  wifi: '\u{1F4F6}',
  'free wifi': '\u{1F4F6}',
  parking: '\u{1F17F}\uFE0F',
  'free parking': '\u{1F17F}\uFE0F',
  spa: '\u{1F486}',
  gym: '\u{1F3CB}\uFE0F',
  fitness: '\u{1F3CB}\uFE0F',
  'fitness center': '\u{1F3CB}\uFE0F',
  restaurant: '\u{1F37D}\uFE0F',
  bar: '\u{1F378}',
  'air conditioning': '\u{2744}\uFE0F',
  'pet friendly': '\u{1F415}',
  beach: '\u{1F3D6}\uFE0F',
  yoga: '\u{1F9D8}',
  dive_center: '\u{1F93F}',
  dive_center_nearby: '\u{1F93F}',
  ski_room: '\u{1F3BF}',
  rooftop_bar: '\u{1F378}',
  garden: '\u{1F33F}',
  valley_view: '\u{1F3DE}\uFE0F',
  lake_view: '\u{1F3DE}\uFE0F',
  horseback: '\u{1F434}',
  guided_hikes: '\u{1F97E}',
};

/**
 * Get inline amenity icons with labels (max 3) for hotel tiles
 */
function getAmenityIconsWithLabels(tile: Tile): Array<{ icon: string; label: string }> {
  const meta = tile.meta as Record<string, unknown> | undefined;
  const amenities = (meta?.amenities as string[]) || [];
  const result: Array<{ icon: string; label: string }> = [];
  const seenIcons = new Set<string>();

  for (const amenity of amenities) {
    const key = amenity.toLowerCase();
    const icon = AMENITY_ICONS[key];
    if (icon && !seenIcons.has(icon)) {
      seenIcons.add(icon);
      const label = amenity.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase());
      result.push({ icon, label });
      if (result.length >= 3) break;
    }
  }

  return result;
}

/**
 * Render star rating as repeated stars for hotels
 */
function renderStarRating(rating: number): string {
  const stars = Math.round(rating);
  return '\u2605'.repeat(Math.min(stars, 5));
}

/**
 * Get amenities from tile meta (for inline expansion)
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
 * Get cancellation text (for inline expansion)
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
 * Get check-in/out times (for inline expansion)
 */
function getCheckTimes(tile: Tile): { checkIn?: string; checkOut?: string } {
  const meta = tile.meta as Record<string, unknown> | undefined;
  return {
    checkIn: typeof meta?.check_in === 'string' ? meta.check_in : undefined,
    checkOut: typeof meta?.check_out === 'string' ? meta.check_out : undefined,
  };
}

export interface MiniCardContentProps {
  tile: Tile;
  isSaved: boolean;
  perks: string[];
  onSaveClick: (e: MouseEvent) => void;
  onOpenStaysSettings?: () => void;
  saveLabel?: string;
}

export function MiniCardContent({
  tile,
  isSaved,
  perks,
  onSaveClick,
  onOpenStaysSettings,
  saveLabel,
}: MiniCardContentProps) {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);

  const priceDisplay = useMemo(() => formatTilePrice(tile), [tile]);
  const amenityIcons = useMemo(() => getAmenityIconsWithLabels(tile), [tile]);
  const activityMeta = useMemo(() => {
    if (tile.type !== 'activity') return null;
    const m = tile.meta as Record<string, unknown> | undefined;
    if (!m) return null;
    return {
      category: typeof m.category === 'string' ? m.category : undefined,
      durationHours: typeof m.duration_hours === 'number' ? m.duration_hours : undefined,
      timeOfDay: typeof m.time_of_day === 'string' ? m.time_of_day : undefined,
      description: typeof m.description === 'string' && m.description ? m.description : undefined,
    };
  }, [tile]);

  const isFlight = isFlightType(tile.type || '');
  const meta = tile.meta as Record<string, unknown> | undefined;
  const logicHook = (meta?.logic_hook as string) || undefined;

  const amenities = useMemo(() => getAmenities(tile), [tile]);
  const cancellationText = useMemo(() => getCancellationText(tile), [tile]);
  const checkTimes = useMemo(() => getCheckTimes(tile), [tile]);

  const handleQuickFactsToggle = useCallback(
    (e: MouseEvent) => {
      e.stopPropagation();
      setIsExpanded((prev) => !prev);
    },
    []
  );

  const quickFactsPanelId = `quickfacts-${tile.id}`;

  return (
    <>
      {/* Main content area */}
      <div className="flex items-start gap-4 p-4">
        {/* Thumbnail */}
        <div className={cn(
          'relative flex-shrink-0 overflow-hidden',
          isFlight
            ? 'h-12 w-12 rounded-full bg-white flex items-center justify-center'
            : 'h-16 w-16 rounded-md bg-zinc-100 dark:bg-zinc-800'
        )}>
          <img
            src={imageError ? placeholderImageForTile(tile) : (tile.image_url || placeholderImageForTile(tile))}
            alt={tile.title}
            loading="lazy"
            onLoad={() => setImageLoaded(true)}
            onError={() => setImageError(true)}
            className={cn(
              'transition-opacity duration-300',
              isFlight
                ? 'h-10 w-10 object-contain'
                : 'h-full w-full object-cover',
              !imageLoaded && 'opacity-0'
            )}
          />
          {onOpenStaysSettings && isHotelType(tile.type || '') && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onOpenStaysSettings();
              }}
              className={cn(
                'absolute bottom-1 right-1 p-1 rounded',
                'bg-black/60 hover:bg-black/80 backdrop-blur-sm',
                'transition-colors'
              )}
              aria-label="Hotel settings"
            >
              <Settings className="h-3 w-3 text-zinc-300" />
            </button>
          )}
        </div>

        {/* Content */}
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {/* Row 1: Name + Rating + Save */}
          <div className="flex items-start justify-between gap-2">
            <h4 className="line-clamp-1 text-sm font-medium text-zinc-900 dark:text-zinc-100">
              {tile.title}
            </h4>
            <div className="flex shrink-0 items-center gap-2">
              {tile.rating != null && (
                <div className="flex items-center gap-0.5 text-xs">
                  {isHotelType(tile.type || '') ? (
                    <span className="text-zinc-500 dark:text-zinc-300">{renderStarRating(tile.rating)}</span>
                  ) : (
                    <>
                      <span className="text-zinc-500 dark:text-zinc-300">{'\u2605'}</span>
                      <span className="text-zinc-500 dark:text-zinc-400">{tile.rating.toFixed(1)}</span>
                    </>
                  )}
                </div>
              )}
              {/* Save button */}
              <button
                type="button"
                onClick={onSaveClick}
                className={cn(
                  'flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors',
                  isSaved
                    ? 'bg-emerald-500/20 text-emerald-600 dark:text-emerald-400'
                    : 'text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100'
                )}
              >
                <Heart
                  className={cn('h-3 w-3', isSaved && 'fill-emerald-400')}
                />
                {isSaved ? 'In Trip' : (saveLabel ?? 'Add to Trip')}
              </button>
            </div>
          </div>

          {/* Row 2: Area + Amenity Icons */}
          {(tile.location_label || amenityIcons.length > 0) && (
            <div className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
              {tile.location_label && (
                <span className="line-clamp-1">{tile.location_label}</span>
              )}
              {amenityIcons.length > 0 && (
                <>
                  {tile.location_label && <span className="text-zinc-300 dark:text-zinc-600">&middot;</span>}
                  <span className="flex gap-0.5">
                    {amenityIcons.map(({ icon, label }) => (
                      <span key={label} title={label} >{icon}</span>
                    ))}
                  </span>
                </>
              )}
            </div>
          )}

          {/* Activity metadata badges (compact) */}
          {activityMeta && (
            <div className="flex flex-wrap items-center gap-1.5">
              {activityMeta.category && (
                <span className={`rounded px-1.5 py-0.5 ${DS.textSize.micro} font-medium uppercase tracking-wide bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400`}>
                  {activityMeta.category}
                </span>
              )}
              {activityMeta.durationHours != null && (
                <span className={`${DS.textSize.micro} text-zinc-500 dark:text-zinc-400 inline-flex items-center gap-0.5`}>
                  <Clock className="h-2.5 w-2.5" />
                  {activityMeta.durationHours}h
                </span>
              )}
              {activityMeta.timeOfDay && (
                <span className={`${DS.textSize.micro} text-zinc-500 dark:text-zinc-400 inline-flex items-center gap-0.5`}>
                  {activityMeta.timeOfDay === 'morning' && <Sun className="h-2.5 w-2.5" />}
                  {activityMeta.timeOfDay === 'afternoon' && <Sunset className="h-2.5 w-2.5" />}
                  {activityMeta.timeOfDay === 'evening' && <Moon className="h-2.5 w-2.5" />}
                  {activityMeta.timeOfDay.charAt(0).toUpperCase() + activityMeta.timeOfDay.slice(1)}
                </span>
              )}
            </div>
          )}

          {/* Activity description (compact) */}
          {activityMeta?.description && (
            <p className={`${DS.textSize.mini} text-zinc-500 dark:text-zinc-400 line-clamp-1`}>
              {activityMeta.description}
            </p>
          )}

          {/* Row 3: Perk chips */}
          {perks.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {perks.map((perk) => (
                <span
                  key={perk}
                  className={cn(
                    `rounded px-1.5 py-0.5 ${DS.textSize.micro} font-medium`,
                    perk === 'Free cancel'
                      ? 'bg-emerald-500/20 text-emerald-700 dark:text-emerald-400'
                      : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400'
                  )}
                >
                  {perk}
                </span>
              ))}
            </div>
          )}

          {/* Row 4: Price */}
          <div className="mt-1">
            <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {priceDisplay}
            </span>
          </div>

          {/* Logic Hook Chip for flights (Safety Shield) */}
          {isFlight && logicHook && (
            <div className="mt-2">
              <span
                className={cn(
                  `rounded px-1.5 py-0.5 ${DS.textSize.micro} font-medium inline-flex items-center gap-1`,
                  meta?.is_safe === false
                    ? 'bg-zinc-500/15 text-zinc-400 border border-zinc-500/20'
                    : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/20'
                )}
              >
                {logicHook}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Quick facts toggle row */}
      <div className="border-t border-zinc-200/50 dark:border-white/10">
        <button
          type="button"
          onClick={handleQuickFactsToggle}
          aria-expanded={isExpanded}
          aria-controls={quickFactsPanelId}
          className="flex w-full items-center gap-1.5 px-3 py-2 min-h-[44px] text-xs text-zinc-500 dark:text-zinc-400 transition-colors hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100/50 dark:hover:bg-white/5"
        >
          <ChevronDown
            className={cn(
              'h-3 w-3 transition-transform duration-200',
              isExpanded && 'rotate-180'
            )}
          />
          <span>Quick facts</span>
        </button>
      </div>

      {/* Inline expanded content */}
      {isExpanded && (
        <div
          id={quickFactsPanelId}
          className="border-t border-zinc-200/50 dark:border-white/10 px-3 pb-3 pt-2 space-y-2"
        >
          {(cancellationText || checkTimes.checkIn || checkTimes.checkOut) && (
            <div className="space-y-1">
              <h5 className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
                Key facts
              </h5>
              <ul className="space-y-0.5 text-xs text-zinc-900 dark:text-zinc-100">
                {checkTimes.checkIn && (
                  <li>&#8226; Check-in: {checkTimes.checkIn}</li>
                )}
                {checkTimes.checkOut && (
                  <li>&#8226; Check-out: {checkTimes.checkOut}</li>
                )}
                {cancellationText && <li>&#8226; {cancellationText}</li>}
              </ul>
            </div>
          )}

          {amenities.length > 0 && (
            <div className="space-y-1">
              <h5 className="text-xs font-medium text-zinc-500 dark:text-zinc-400 uppercase tracking-wide">
                Amenities
              </h5>
              <div className="flex flex-wrap gap-1">
                {amenities.slice(0, 4).map((amenity) => (
                  <span
                    key={amenity}
                    className={`rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 ${DS.textSize.micro} text-zinc-600 dark:text-zinc-400`}
                  >
                    {amenity}
                  </span>
                ))}
                {amenities.length > 4 && (
                  <span className={`rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 ${DS.textSize.micro} text-zinc-500/70 dark:text-zinc-500`}>
                    +{amenities.length - 4} more
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Provider + Booking Data Tooltip */}
          <div className="flex items-center justify-between">
            {tile.provider && (
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                via {tile.provider}
              </p>
            )}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    onClick={(e) => e.stopPropagation()}
                    className={`flex items-center gap-1 rounded px-1.5 py-0.5 ${DS.textSize.micro} text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors`}
                  >
                    <Code2 className="h-3 w-3" />
                    <span>API</span>
                  </button>
                </TooltipTrigger>
                <TooltipContent side="top" className="max-w-xs">
                  <p className={`${DS.textSize.micro} text-zinc-500 dark:text-zinc-400 mb-1 font-medium`}>
                    Booking API Payload
                  </p>
                  <pre className={`${DS.textSize.micro} font-mono bg-zinc-100/50 dark:bg-zinc-800/50 rounded p-2 overflow-auto max-h-40`}>
                    {JSON.stringify(getDeepLinkParams(tile), null, 2)}
                  </pre>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        </div>
      )}
    </>
  );
}
