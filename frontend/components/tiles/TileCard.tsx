/* eslint no-unused-vars: ["error", { "args": "none" }] */
import { Check, Clock, Heart, MapPin, Moon, Settings, Sun, Sunset } from 'lucide-react';
import {
  type KeyboardEvent,
  memo,
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

/**
 * Amenity icon mapping for inline display (max 3 shown)
 */
const AMENITY_ICONS: Record<string, string> = {
  pool: '🏊',
  'swimming pool': '🏊',
  breakfast: '🍳',
  'breakfast included': '🍳',
  wifi: '📶',
  'free wifi': '📶',
  parking: '🅿️',
  'free parking': '🅿️',
  spa: '💆',
  gym: '🏋️',
  fitness: '🏋️',
  'fitness center': '🏋️',
  restaurant: '🍽️',
  bar: '🍸',
  'air conditioning': '❄️',
  'pet friendly': '🐕',
  // Curated destination amenities
  beach: '🏖️',
  yoga: '🧘',
  dive_center: '🤿',
  dive_center_nearby: '🤿',
  ski_room: '🎿',
  rooftop_bar: '🍸',
  garden: '🌿',
  valley_view: '🏞️',
  lake_view: '🏞️',
  horseback: '🐴',
  guided_hikes: '🥾',
};

import { TaxesFeesTooltip } from '@/components/tiles/TaxesFeesTooltip';
import { Button } from '@/components/ui/button';
import { Card, CardBody } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { apiFetch } from '@/lib/api';
import { debugLog } from '@/lib/debug';
import { placeholderImageForTile } from '@/lib/placeholders';
import { getDeepLinkParams } from '@/lib/tileUtils';
import { cn, isFlightType } from '@/lib/utils';
import { usePreferenceActions, useTilePreference } from '@/state/documentStore';
import type { Tile } from '@/types/tile';

type TileCardProps = {
  tile: Tile;
  branchId?: string;
  isSelected?: boolean;
  onToggleSelect?: (tile: Tile) => void;
  /** Callback to show a toast notification when tile is selected */
  onSelectionToast?: (message: string) => void;
  /** Whether this tile was saved/shortlisted (show "Saved" badge) */
  isSaved?: boolean;
  /** Callback to open category-wide stays/hotel settings sheet */
  onOpenStaysSettings?: () => void;
};

/**
 * Extract features from tile metadata.
 * Returns empty array if no features - no mock data.
 */
const getFeaturesForTile = (tile: Tile): string[] => {
  const meta = tile.meta as Record<string, unknown> | undefined;

  // Use features from backend if available
  if (meta?.features && Array.isArray(meta.features)) {
    return meta.features as string[];
  }

  // For flights, extract real metadata as features
  if (isFlightType(tile.type || '')) {
    const features: string[] = [];
    if (typeof meta?.stops === 'string') features.push(meta.stops);
    if (typeof meta?.fare_class === 'string') features.push(meta.fare_class);
    if (typeof meta?.duration === 'string') features.push(meta.duration);
    return features;
  }

  // No mock fallback - return empty array
  return [];
};

/**
 * Get inline amenity icons with labels (max 3) for hotel tiles
 */
const getAmenityIconsWithLabels = (tile: Tile): Array<{ icon: string; label: string }> => {
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
};

/**
 * Render star rating as repeated stars for hotels
 */
const renderStarRating = (rating: number): string => {
  const stars = Math.round(rating);
  return '★'.repeat(Math.min(stars, 5));
};

/**
 * Extract relevance badges from tile attributes.
 * Used for specialist relevance indicators (max 2 badges).
 */
const getRelevanceBadges = (tile: Tile): string[] => {
  const badges: string[] = [];
  const meta = tile.meta as Record<string, unknown> | undefined;

  // Free cancellation
  if (tile.is_refundable === true) {
    badges.push('Free cancellation');
  }

  // Breakfast included
  if (meta?.breakfast_included === true) {
    badges.push('Breakfast included');
  }

  // Pool access (common amenity for diving/resort trips)
  if (meta?.has_pool === true) {
    badges.push('Pool');
  }

  // Specialist badges from backend (future)
  if (meta?.specialist_badges && Array.isArray(meta.specialist_badges)) {
    badges.push(...(meta.specialist_badges as string[]));
  }

  // Return max 2 badges
  return badges.slice(0, 2);
};

export const TileCard = memo(function TileCard({
  tile,
  branchId,
  isSelected,
  onToggleSelect,
  onSelectionToast,
  isSaved = false,
  onOpenStaysSettings,
}: TileCardProps) {
  // Heart preference system - connects to Zustand store with sessionStorage persistence
  const isPreferred = useTilePreference(tile.id);
  const { toggleTilePreference } = usePreferenceActions();
  // Track just-selected state for animation feedback
  const [justSelected, setJustSelected] = useState(false);
  // Track heart animation state
  const [heartAnimating, setHeartAnimating] = useState(false);
  useEffect(() => {
    if (!heartAnimating) return;
    const timer = setTimeout(() => setHeartAnimating(false), 200);
    return () => clearTimeout(timer);
  }, [heartAnimating]);
  // Track previous selection state to detect transitions
  const prevSelectedRef = useRef(isSelected);
  // Tier 11.7: Track image loading state for skeleton feedback
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageError, setImageError] = useState(false);
  // AbortController ref for fire-and-forget click tracking
  const trackAbortRef = useRef<AbortController | null>(null);

  // Abort any in-flight click tracking on unmount
  useEffect(() => {
    return () => { trackAbortRef.current?.abort(); };
  }, []);

  const features = useMemo(() => getFeaturesForTile(tile), [tile]);
  const relevanceBadges = useMemo(() => getRelevanceBadges(tile), [tile]);
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
  const isHotel = tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay');

  // Detect when tile becomes selected and trigger animation
  useEffect(() => {
    // Only animate when going from unselected to selected
    if (isSelected && !prevSelectedRef.current) {
      setJustSelected(true);
      // Reset animation state after animation completes
      const timer = setTimeout(() => setJustSelected(false), 300);
      return () => clearTimeout(timer);
    }
    prevSelectedRef.current = isSelected;
    return undefined;
  }, [isSelected]);

  // Memoize click tracking payload to avoid recreating on each render
  const trackClick = useCallback(() => {
    // Abort any prior in-flight tracking request
    trackAbortRef.current?.abort();
    const controller = new AbortController();
    trackAbortRef.current = controller;

    apiFetch('/api/tiles/click', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tile_id: tile.id,
        branch_id: branchId ?? null,
        user_id: null,
      }),
      signal: controller.signal,
    }).catch((error) => {
      if (error instanceof Error && error.name === 'AbortError') return;
      if (process.env.NODE_ENV !== 'production') {
        console.warn('Click tracking failed:', error);
      }
    });
  }, [tile.id, branchId]);

  const handleClick = useCallback(() => {
    // Fire-and-forget click tracking (session is sent via cookie)
    trackClick();
    // Open partner deeplink immediately
    window.open(tile.deeplink_url, '_blank', 'noopener,noreferrer');
  }, [trackClick, tile.deeplink_url]);

  const handleToggleSelect = useCallback(
    (event: MouseEvent | KeyboardEvent<HTMLDivElement>) => {
      event.preventDefault();
      event.stopPropagation();

      // Show toast if we're selecting (not deselecting) and callback is provided
      if (!isSelected && onSelectionToast) {
        // Truncate long titles for the toast message
        const displayTitle = tile.title.length > 30 ? tile.title.slice(0, 27) + '...' : tile.title;
        onSelectionToast(`Added ${displayTitle} to your trip`);
      }

      onToggleSelect?.(tile);
    },
    [onToggleSelect, tile, isSelected, onSelectionToast]
  );

  const handlePreferenceToggle = useCallback((event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
    debugLog('[TileCard] 💜 Heart clicked for tile:', tile.id);
    // Trigger scale animation (cleared by heartAnimating useEffect)
    setHeartAnimating(true);
    // Toggle in Zustand store (persists to DB via PATCH)
    toggleTilePreference(tile.id);
  }, [toggleTilePreference, tile.id]);

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      if (event.key === 'Enter' || event.key === ' ') {
        handleToggleSelect(event);
      }
    },
    [handleToggleSelect]
  );

  const handleViewDetailsClick = useCallback(
    (event: MouseEvent) => {
      event.stopPropagation();
      handleClick();
    },
    [handleClick]
  );

  return (
    <Card
      data-tile-id={tile.id}
      onClick={handleToggleSelect}
      className={cn(
        'bg-card group relative flex h-full flex-col overflow-hidden rounded-2xl border shadow-sm transition-all hover:shadow-md',
        isSelected ? 'ring-primary border-primary ring-2' : 'border-border',
        // Scale animation on selection for visual feedback (Tier 10.19)
        justSelected && 'scale-[1.02]',
        'transition-transform duration-200 ease-out'
      )}
      role="button"
      tabIndex={0}
      onKeyDown={handleKeyDown}
    >
      <div className={cn(
        'relative w-full overflow-hidden',
        isFlight ? 'aspect-[16/10] bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center' : 'aspect-[16/9]'
      )}>
        {/* Tier 11.7: Skeleton shown while image loads */}
        {!imageLoaded && !isFlight && (
          <Skeleton className="absolute inset-0 h-full w-full rounded-none" />
        )}
        {/* Flight tiles: white circle with airline logo */}
        {isFlight ? (
          <div className="w-16 h-16 rounded-full bg-white flex items-center justify-center shadow-sm">
            <img
              src={imageError ? placeholderImageForTile(tile) : (tile.image_url || placeholderImageForTile(tile))}
              alt={tile.title}
              loading="lazy"
              onLoad={() => setImageLoaded(true)}
              onError={() => setImageError(true)}
              className={cn(
                'w-12 h-12 object-contain transition-opacity duration-300',
                !imageLoaded && 'opacity-0'
              )}
            />
          </div>
        ) : (
          <img
            src={imageError ? placeholderImageForTile(tile) : (tile.image_url || placeholderImageForTile(tile))}
            alt={tile.title}
            loading="lazy"
            onLoad={() => setImageLoaded(true)}
            onError={() => setImageError(true)}
            className={cn(
              'h-full w-full object-cover transition duration-700 group-hover:scale-105',
              !imageLoaded && 'opacity-0'
            )}
          />
        )}
        {!isFlight && <div className="absolute inset-0 bg-gradient-to-t from-black/40 via-transparent to-transparent" />}

        {/* Heart preference button - emerald when preferred, zinc outline when not */}
        <TooltipProvider delayDuration={300}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className={cn(
                  'absolute right-3 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full transition-all touch-manipulation',
                  'bg-black/40 backdrop-blur-sm',
                  'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50',
                  heartAnimating && 'scale-110'
                )}
                onClick={handlePreferenceToggle}
                aria-label={isPreferred ? 'Remove from preferences' : 'Add to preferences'}
                aria-pressed={isPreferred}
              >
                <Heart
                  className={cn(
                    'h-5 w-5 transition-colors',
                    isPreferred
                      ? 'fill-emerald-500 stroke-emerald-500'
                      : 'stroke-zinc-400 fill-transparent hover:stroke-zinc-300'
                  )}
                />
              </button>
            </TooltipTrigger>
            <TooltipContent side="left" className="text-xs">
              {isPreferred ? 'Remove preference' : 'Prefer this option'}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {/* Settings gear for hotel/stay tiles - opens category-wide StaysSheet */}
        {onOpenStaysSettings && (tile.type === 'hotel' || tile.type?.toLowerCase().includes('stay')) && (
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className={cn(
                    'absolute right-12 top-3 inline-flex h-8 w-8 items-center justify-center rounded-full transition-all touch-manipulation',
                    'bg-black/40 backdrop-blur-sm hover:bg-black/60',
                    'focus:outline-none focus-visible:ring-2 focus-visible:ring-white/50'
                  )}
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenStaysSettings();
                  }}
                  aria-label="Hotel settings"
                >
                  <Settings className="h-4 w-4 text-zinc-300" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="left" className="text-xs">
                Hotel preferences
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}

        {/* Preferred badge (top-left, emerald pill with heart icon) */}
        {isPreferred && (
          <div className="absolute left-2 top-2 flex items-center gap-1 rounded-full bg-emerald-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
            <Heart className="h-3 w-3 fill-white" />
            Preferred
          </div>
        )}
        {/* Saved badge (from shortlist) - only show if not preferred */}
        {!isPreferred && isSaved && (
          <div className="absolute left-2 top-2 rounded bg-emerald-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
            Saved
          </div>
        )}
        {/* Refundable/Non-refundable badge - Expedia compliance */}
        {!isSaved && tile.is_refundable === false && (
          <div className="absolute left-2 top-2 rounded bg-zinc-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
            Non-refundable
          </div>
        )}
        {!isSaved && tile.is_refundable === true && (
          <div className="absolute left-2 top-2 rounded bg-emerald-500/90 px-2 py-0.5 text-xs font-medium text-white shadow-sm">
            Free cancellation
          </div>
        )}
      </div>

      <CardBody className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex items-start justify-between gap-2">
          <div className="font-display text-foreground text-lg font-semibold leading-tight">
            {tile.title}
          </div>
          {tile.rating != null && (
            <div className="flex shrink-0 items-center gap-1 text-sm font-medium">
              {isHotel ? (
                <span className="text-zinc-500 dark:text-zinc-300">{renderStarRating(tile.rating)}</span>
              ) : (
                <>
                  <span className="text-zinc-500 dark:text-zinc-300">★</span>
                  <span className="text-foreground">{tile.rating.toFixed(1)}</span>
                </>
              )}
            </div>
          )}
        </div>

        {/* Activity metadata badges */}
        {activityMeta && (
          <div className="flex flex-wrap items-center gap-1.5">
            {activityMeta.category && (
              <span className="bg-muted text-muted-foreground inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium uppercase tracking-wide">
                {activityMeta.category}
              </span>
            )}
            {activityMeta.durationHours != null && (
              <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
                <Clock className="h-3 w-3" />
                {activityMeta.durationHours}h
              </span>
            )}
            {activityMeta.timeOfDay && (
              <span className="text-muted-foreground inline-flex items-center gap-1 text-xs">
                {activityMeta.timeOfDay === 'morning' && <Sun className="h-3 w-3" />}
                {activityMeta.timeOfDay === 'afternoon' && <Sunset className="h-3 w-3" />}
                {activityMeta.timeOfDay === 'evening' && <Moon className="h-3 w-3" />}
                {activityMeta.timeOfDay.charAt(0).toUpperCase() + activityMeta.timeOfDay.slice(1)}
              </span>
            )}
          </div>
        )}

        {/* Activity description */}
        {activityMeta?.description && (
          <p className="text-muted-foreground line-clamp-1 text-sm">
            {activityMeta.description}
          </p>
        )}

        {(tile.location_label || amenityIcons.length > 0) && (
          <div className="text-muted-foreground -mt-1 flex items-center gap-1.5 text-sm">
            {tile.location_label && (
              <>
                <MapPin className="h-4 w-4 shrink-0" />
                <span className="line-clamp-1">{tile.location_label}</span>
              </>
            )}
            {amenityIcons.length > 0 && (
              <>
                {tile.location_label && <span className="text-zinc-500">·</span>}
                <span className="flex gap-0.5">
                  {amenityIcons.map(({ icon, label }) => (
                    <span key={label} title={label} >{icon}</span>
                  ))}
                </span>
              </>
            )}
          </div>
        )}

        {/* Specialist relevance badges - max 2, shows key attributes */}
        {relevanceBadges.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 -mt-1">
            {relevanceBadges.map((badge) => (
              <span
                key={badge}
                className="inline-flex items-center gap-1 text-[13px] text-zinc-400"
              >
                <Check className="h-3 w-3 text-emerald-500" />
                {badge}
              </span>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {features.map((feature) => (
            <span
              key={feature}
              className="bg-muted text-muted-foreground inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium"
            >
              {feature}
            </span>
          ))}
        </div>

        <div className="mt-auto flex items-end justify-between pt-2">
          <div className="flex flex-col gap-0.5">
            <span className="text-muted-foreground text-xs">
              {tile.total_inclusive != null ? 'Total from' : 'From'}
            </span>
            <div className="flex items-baseline gap-1">
              <span className="text-zinc-900 dark:text-zinc-100 text-[18px] font-semibold">
                {(tile.total_inclusive ?? tile.price_estimate) != null
                  ? Math.round(tile.total_inclusive ?? tile.price_estimate!).toLocaleString()
                  : ''}
              </span>
              <span className="text-zinc-500 dark:text-zinc-400 text-sm font-medium">{tile.currency}</span>
              {tile.type?.toLowerCase().includes('stay') && !tile.total_inclusive && (
                <span className="text-muted-foreground text-xs">/night</span>
              )}
            </div>
            {(tile.total_inclusive ?? tile.price_estimate) == null && (
              <span className="text-zinc-900 dark:text-zinc-100 text-sm font-semibold">Check price</span>
            )}
            {/* Expedia taxes & fees disclosure with legal tooltip */}
            <TaxesFeesTooltip
              taxAndServiceFee={tile.tax_and_service_fee}
              propertyFee={tile.property_fee}
              currency={tile.currency}
            />
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center gap-2">
              <TooltipProvider delayDuration={400}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-muted-foreground hover:text-foreground"
                      onClick={handleViewDetailsClick}
                    >
                      Details
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent
                    side="top"
                    className="max-w-xs bg-zinc-900 text-zinc-100 text-xs font-mono p-3 rounded-lg shadow-lg"
                  >
                    <div className="text-zinc-400 text-[10px] uppercase tracking-wider mb-1.5">
                      API Params
                    </div>
                    <pre className="whitespace-pre-wrap break-all">
                      {JSON.stringify(getDeepLinkParams(tile), null, 2)}
                    </pre>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
              <Button
                variant="primary"
                size="sm"
                className="bg-emerald-600 hover:bg-emerald-500 text-white font-semibold shadow-sm"
                onClick={handleViewDetailsClick}
              >
                Book
              </Button>
            </div>
            <span className="text-[10px] text-muted-foreground">
              Opens partner site
            </span>
          </div>
        </div>
      </CardBody>
    </Card>
  );
});
