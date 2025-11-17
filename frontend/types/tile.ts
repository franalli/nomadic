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
};
