/**
 * useMapSync
 *
 * Central state management hook for map-itinerary two-way synchronization.
 *
 * Features:
 * - Extracts map items from day cards (itinerary) or specialist sections (POIs)
 * - Tracks active item from scroll spy
 * - Handles marker click → scroll to timeline
 * - Generates route GeoJSON for visualization
 * - Manages layer visibility filters
 *
 * @see docs/ux_unified_architecture.md for specification
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  combineMapItems,
  extractActivityTypes,
  extractMapItemsFromDayCards,
  extractMapItemsFromSections,
  generateRouteGeoJson,
  type MapItem,
} from '@/lib/route-utils';
import type { DayCard, StrategySection } from '@/types/plan-envelope';

import { useScrollSpy } from './useScrollSpy';

// =============================================================================
// Types
// =============================================================================

export interface UseMapSyncOptions {
  /** Day cards from itinerary (PLAN mode) */
  dayCards?: DayCard[];
  /** Strategy sections from specialists (SETUP/Bridge mode) */
  strategySections?: StrategySection[];
  /** Current mode determines data source priority */
  mode: 'setup' | 'plan';
  /** Whether to enable scroll spy (disable during rapid scrolling) */
  enableScrollSpy?: boolean;
}

export interface UseMapSyncReturn {
  // === Map Items ===
  /** Filtered map items to display */
  mapItems: MapItem[];
  /** All map items before filtering */
  allMapItems: MapItem[];

  // === Active State ===
  /** Currently active item ID (from scroll spy) */
  activeItemId: string | null;
  /** Currently hovered day number (for day-based filtering) */
  hoveredDay: number | null;
  /** Set hovered day */
  setHoveredDay: (day: number | null) => void;

  // === Navigation ===
  /** Handle marker click - scrolls to timeline item */
  handleMarkerClick: (itemId: string) => void;
  /** Scroll to a specific item by ID */
  scrollToItem: (itemId: string) => void;

  // === Route Visualization ===
  /** GeoJSON route for line visualization (plan mode only) */
  routeGeoJson: GeoJSON.FeatureCollection | null;

  // === Layer Filtering ===
  /** Set of visible layer types */
  visibleLayers: Set<string>;
  /** Toggle a layer's visibility */
  toggleLayer: (layerType: string) => void;
  /** Show all layers */
  showAllLayers: () => void;
  /** Available layer types (for filter UI) */
  availableTypes: string[];

  // === Computed State ===
  /** Map center point */
  center: { lat: number; lng: number } | null;
  /** Whether map has any items to display */
  hasItems: boolean;
}

// =============================================================================
// Hook Implementation
// =============================================================================

export function useMapSync({
  dayCards = [],
  strategySections,
  mode,
  enableScrollSpy = true,
}: UseMapSyncOptions): UseMapSyncReturn {
  // === Local State ===
  const [hoveredDay, setHoveredDay] = useState<number | null>(null);
  const [visibleLayers, setVisibleLayers] = useState<Set<string>>(new Set());
  const highlightTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup highlight timer on unmount
  useEffect(() => {
    return () => {
      if (highlightTimerRef.current) {
        clearTimeout(highlightTimerRef.current);
      }
    };
  }, []);

  // === Extract Map Items ===
  const allMapItems = useMemo((): MapItem[] => {
    if (mode === 'setup') {
      // SETUP mode: POIs from specialist recommendations
      return extractMapItemsFromSections(strategySections);
    }

    // PLAN mode: Blocks from day cards + specialist POIs
    const itineraryItems = extractMapItemsFromDayCards(dayCards);
    const specialistItems = extractMapItemsFromSections(strategySections);

    return combineMapItems(itineraryItems, specialistItems);
  }, [dayCards, strategySections, mode]);

  // === Available Types (for filter UI) ===
  const availableTypes = useMemo(
    () => extractActivityTypes(allMapItems),
    [allMapItems]
  );

  // === Initialize Visible Layers ===
  // Show all layers by default when types change
  useEffect(() => {
    if (visibleLayers.size === 0 && availableTypes.length > 0) {
      setVisibleLayers(new Set(availableTypes));
    }
  }, [availableTypes, visibleLayers.size]);

  // === Filter Items ===
  const mapItems = useMemo(() => {
    let items = allMapItems;

    // Day filter (when hovering a specific day)
    if (hoveredDay !== null) {
      items = items.filter(
        (item) => item.dayNumber === hoveredDay || item.dayNumber === undefined
      );
    }

    // Layer filter (if any layers are hidden)
    if (visibleLayers.size > 0 && visibleLayers.size < availableTypes.length) {
      items = items.filter((item) => visibleLayers.has(item.type));
    }

    return items;
  }, [allMapItems, hoveredDay, visibleLayers, availableTypes.length]);

  // === Scroll Spy ===
  const itemIds = useMemo(
    () => (enableScrollSpy ? mapItems.map((item) => item.id) : []),
    [mapItems, enableScrollSpy]
  );
  const activeItemId = useScrollSpy(itemIds);

  // === Route GeoJSON (plan mode only) ===
  const routeGeoJson = useMemo(() => {
    if (mode !== 'plan' || dayCards.length === 0) return null;
    return generateRouteGeoJson(dayCards);
  }, [dayCards, mode]);

  // === Center Calculation ===
  const center = useMemo(() => {
    if (mapItems.length === 0) return null;

    const sum = mapItems.reduce(
      (acc, item) => ({
        lat: acc.lat + item.coordinates.lat,
        lng: acc.lng + item.coordinates.lng,
      }),
      { lat: 0, lng: 0 }
    );

    return {
      lat: sum.lat / mapItems.length,
      lng: sum.lng / mapItems.length,
    };
  }, [mapItems]);

  // === Navigation Handlers ===

  /**
   * Scroll to a timeline item by ID.
   * Highlights the item briefly after scrolling.
   */
  const scrollToItem = useCallback((itemId: string) => {
    const element = document.getElementById(`timeline-item-${itemId}`);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });

      // Clear any existing highlight timer
      if (highlightTimerRef.current) {
        clearTimeout(highlightTimerRef.current);
      }

      // Add highlight effect
      element.classList.add('ring-2', 'ring-emerald-500', 'transition-all');
      highlightTimerRef.current = setTimeout(() => {
        element.classList.remove('ring-2', 'ring-emerald-500');
        highlightTimerRef.current = null;
      }, 2000);
    }
  }, []);

  /**
   * Handle marker click - scroll to corresponding timeline item.
   */
  const handleMarkerClick = useCallback(
    (itemId: string) => {
      scrollToItem(itemId);
    },
    [scrollToItem]
  );

  // === Layer Filter Handlers ===

  /**
   * Toggle a layer's visibility.
   */
  const toggleLayer = useCallback((layerType: string) => {
    setVisibleLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layerType)) {
        next.delete(layerType);
      } else {
        next.add(layerType);
      }
      return next;
    });
  }, []);

  /**
   * Show all layers.
   */
  const showAllLayers = useCallback(() => {
    setVisibleLayers(new Set(availableTypes));
  }, [availableTypes]);

  // === Return ===
  return {
    // Map Items
    mapItems,
    allMapItems,

    // Active State
    activeItemId,
    hoveredDay,
    setHoveredDay,

    // Navigation
    handleMarkerClick,
    scrollToItem,

    // Route Visualization
    routeGeoJson,

    // Layer Filtering
    visibleLayers,
    toggleLayer,
    showAllLayers,
    availableTypes,

    // Computed State
    center,
    hasItems: mapItems.length > 0,
  };
}
