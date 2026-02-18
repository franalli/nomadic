/**
 * Tile types for the frontend.
 *
 * Note: Generated types are available in './generated.ts' via `npm run types:generate`.
 * This manual definition uses a looser `type: string` for flexibility in tile classification.
 */

type TileProvider = 'expedia' | 'booking' | 'unknown';

export type Tile = {
  id: string;
  type: string;
  partner?: string;
  partner_product_id?: string;
  title: string;
  subtitle?: string;
  image_url?: string;
  price_estimate?: number;
  live_price?: number;
  currency: string;
  /** Price basis: 'per_night', 'per_person', 'per_trip', etc. */
  price_basis?: string;
  is_estimate_only?: boolean;
  deeplink_url: string;
  rating?: number;
  review_count?: number;
  location_label?: string;
  geo?: { lat: number; lng: number };
  tags?: string[];
  availability_status?: 'available' | 'low' | 'unknown' | 'not_available';
  meta?: Record<string, unknown>;
  score?: number;
  source?: string;
  source_agent?: string;

  // Expedia Rapid API pricing fields
  /** Total price including all taxes and fees (property_inclusive from Expedia) */
  total_inclusive?: number;
  /** Combined taxes and service fees */
  tax_and_service_fee?: number;
  /** Property-collected fees */
  property_fee?: number;
  /** Whether the booking is refundable */
  is_refundable?: boolean;
  /** Brief cancellation policy summary */
  cancel_policy_summary?: string;
  /** Which booking provider this tile comes from */
  provider?: TileProvider;
};

export interface PartnerPrice {
  partner: string;
  price: number;
  currency: string;
  url?: string;
  logo?: string;
  isBestPrice?: boolean;
}

export type TileSelection = {
  stay?: Tile;
  flight?: Tile;
  activities: Tile[];
};
