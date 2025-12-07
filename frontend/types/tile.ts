/**
 * Tile types for the frontend.
 *
 * Note: Generated types are available in './generated.ts' via `npm run types:generate`.
 * This manual definition uses a looser `type: string` for flexibility in tile classification.
 */

export type Tile = {
  id: string;
  type: string;
  title: string;
  subtitle?: string;
  image_url?: string;
  price_estimate?: number;
  currency: string;
  deeplink_url: string;
  rating?: number;
  location_label?: string;
  meta?: Record<string, unknown>;
};

export type TileSelection = {
  stay?: Tile;
  flight?: Tile;
  activities: Tile[];
};
