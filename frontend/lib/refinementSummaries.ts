import {
  type ActivitySettings,
  type BookingTypeState,
  type FlightSettings,
  type HotelSettings,
  isBookingEnabled,
  type TransportSettings,
} from '@/types/document';

/**
 * Generates a compact summary string for flight settings.
 * Example: "Round trip · Economy" or "One way · Business · Direct"
 */
export function getFlightsSummary(
  settings: FlightSettings,
  enabled: boolean | BookingTypeState
): string | undefined {
  if (!isBookingEnabled(enabled)) return undefined;

  const cabinLabels: Record<FlightSettings['cabin_class'], string> = {
    economy: 'Economy',
    premium_economy: 'Premium',
    business: 'Business',
    first: 'First',
  };

  const parts = [
    settings.round_trip ? 'Round trip' : 'One way',
    cabinLabels[settings.cabin_class],
  ];

  if (settings.direct_only) {
    parts.push('Direct');
  }

  return parts.join(' · ');
}

/**
 * Generates a compact summary string for hotel settings.
 * Example: "3+ stars · WiFi, Pool" or "4+ stars"
 */
export function getHotelsSummary(
  settings: HotelSettings,
  enabled: boolean | BookingTypeState
): string | undefined {
  if (!isBookingEnabled(enabled)) return undefined;

  const parts: string[] = [];

  if (settings.min_stars > 0) {
    parts.push(`${settings.min_stars}+ stars`);
  }

  if (settings.amenities.length > 0) {
    const amenityLabels: Record<string, string> = {
      wifi: 'WiFi',
      pool: 'Pool',
      parking: 'Parking',
      gym: 'Gym',
      spa: 'Spa',
      breakfast: 'Breakfast',
      pet_friendly: 'Pets OK',
    };

    const formatted = settings.amenities.map((a) => amenityLabels[a] || a);
    if (formatted.length <= 4) {
      parts.push(formatted.join(', '));
    } else {
      parts.push(`${formatted.slice(0, 2).join(', ')} +${formatted.length - 2}`);
    }
  }

  return parts.length > 0 ? parts.join(' · ') : 'Enabled';
}

/**
 * Generates a compact summary string for transport settings.
 * Example: "Car, Train" or "Bus"
 */
export function getTransportSummary(
  settings: TransportSettings,
  enabled: boolean | BookingTypeState
): string | undefined {
  if (!isBookingEnabled(enabled)) return undefined;

  const modes: string[] = [];
  if (settings.car) modes.push('Car');
  if (settings.train) modes.push('Train');
  if (settings.bus) modes.push('Bus');

  return modes.length > 0 ? modes.join(', ') : 'Enabled';
}

/**
 * Generates a compact summary string for activity settings.
 * Example: "Tours, Outdoor" or "3 categories"
 */
export function getActivitiesSummary(
  settings: ActivitySettings,
  enabled: boolean | BookingTypeState
): string | undefined {
  const isEnabled = isBookingEnabled(enabled);
  if (!isEnabled && settings.categories.length === 0) return undefined;

  if (settings.categories.length === 0) {
    return isEnabled ? 'Enabled' : undefined;
  }

  if (settings.categories.length <= 2) {
    return settings.categories
      .map((c) => c.charAt(0).toUpperCase() + c.slice(1))
      .join(', ');
  }

  return `${settings.categories.length} categories`;
}

/**
 * Generates a compact summary string for travelers.
 * Example: "2 adults, 1 child" or "2 adults · Assistance"
 */
export function getTravelersSummary(
  adults?: number | null,
  children?: number | null,
  requiresAssistance?: boolean | null
): string | undefined {
  const parts: string[] = [];

  if (adults && adults > 0) {
    parts.push(`${adults} adult${adults !== 1 ? 's' : ''}`);
  }

  if (children && children > 0) {
    parts.push(`${children} child${children !== 1 ? 'ren' : ''}`);
  }

  if (requiresAssistance) {
    parts.push('Assistance');
  }

  return parts.length > 0 ? parts.join(', ') : undefined;
}
