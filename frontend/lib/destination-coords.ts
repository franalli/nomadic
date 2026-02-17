/**
 * Demo POIs for YC demo - curated dive sites and hiking trails.
 * Used as fallback when backend doesn't provide coordinates in content_added.
 */
export const DEMO_POIS: Record<string, Array<{
  lat: number;
  lng: number;
  title: string;
  type: string;
  specialist: string;
}>> = {
  Bali: [
    { lat: -8.2775, lng: 115.5300, title: 'USAT Liberty Wreck', type: 'activity', specialist: 'diving' },
    { lat: -8.5234, lng: 115.5101, title: 'Padang Bai - Blue Lagoon', type: 'activity', specialist: 'diving' },
    { lat: -8.4029, lng: 115.4221, title: 'Amed - Jemeluk Bay', type: 'activity', specialist: 'diving' },
    { lat: -8.2936, lng: 115.3988, title: 'Mt Batur Sunrise Trek', type: 'activity', specialist: 'hiking' },
    { lat: -8.3558, lng: 115.3348, title: 'Campuhan Ridge Walk', type: 'activity', specialist: 'hiking' },
  ],
};
