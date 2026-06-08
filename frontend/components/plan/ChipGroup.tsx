'use client';

import type {
  ActivitySettings,
  FlightSettings,
  HotelSettings,
} from '@/types/document';
import type { DayCard } from '@/types/plan-envelope';

import { resolveBlockCategory } from './tripSummaryUtils';

export type { ModuleState } from './ModuleChip';
export { ModuleChip } from './ModuleChip';
export { SetupCoreChip } from './SetupCoreChip';

export const isFlightCustom = (settings?: FlightSettings): boolean => {
  if (!settings) return false;
  return (
    settings.cabin_class !== 'economy' ||
    settings.direct_only === true ||
    settings.round_trip === false
  );
};

export const isHotelCustom = (settings?: HotelSettings): boolean => {
  if (!settings) return false;
  return (
    (settings.min_stars !== undefined && settings.min_stars > 0) ||
    (settings.amenities !== undefined && settings.amenities.length > 0)
  );
};

export const isActivityCustom = (
  settings?: ActivitySettings,
  fallbackCategories: string[] = []
): boolean => {
  if (!settings) return fallbackCategories.length > 0;
  const categories =
    settings.categories && settings.categories.length > 0
      ? settings.categories
      : fallbackCategories;
  return categories.length > 0;
};

export function getFlightChipSummary(settings?: FlightSettings): string | null {
  if (!settings) return null;

  const tokens: string[] = [];

  if (settings.direct_only) {
    tokens.push('Nonstop');
  }

  if (settings.cabin_class && settings.cabin_class !== 'economy') {
    const cabinLabels: Record<string, string> = {
      premium_economy: 'Premium',
      business: 'Business',
      first: 'First',
    };
    tokens.push(cabinLabels[settings.cabin_class] || settings.cabin_class);
  }

  if (settings.round_trip === false) {
    tokens.push('One-way');
  }

  return tokens.join(' · ') || null;
}

export function getHotelChipSummary(settings?: HotelSettings): string | null {
  if (!settings) return null;

  const tokens: string[] = [];

  if (settings.min_stars && settings.min_stars > 0) {
    tokens.push(`${settings.min_stars}★+`);
  }

  if (settings.amenities && settings.amenities.length > 0) {
    const amenityLabels: Record<string, string> = {
      wifi: 'WiFi',
      pool: 'Pool',
      parking: 'Parking',
      gym: 'Gym',
      spa: 'Spa',
      breakfast: 'Breakfast',
      pet_friendly: 'Pets OK',
      beachfront: 'Beachfront',
    };
    for (const amenity of settings.amenities) {
      tokens.push(
        amenityLabels[amenity] || amenity.charAt(0).toUpperCase() + amenity.slice(1)
      );
    }
  }

  if (tokens.length === 0) return null;
  if (tokens.length <= 4) return tokens.join(' · ');
  return `${tokens.slice(0, 2).join(' · ')} +${tokens.length - 2}`;
}

// Mirror the day-card badges: resolveBlockCategory is the single badge resolver
// (delegates to resolveActivityCategory + buffer guard). No constraint-derived
// categories -- those are not shown as badges and previously made the chip row
// disagree with the Activities modal.
export function inferCategoriesFromDayCards(dayCards: DayCard[] | undefined): string[] {
  if (!dayCards || dayCards.length === 0) return [];
  const inferred = new Set<string>();
  dayCards.forEach((card) => {
    card.blocks?.forEach((block) => {
      const category = resolveBlockCategory(block);
      if (category) inferred.add(category);
    });
  });
  return Array.from(inferred);
}
