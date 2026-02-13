/**
 * Hardcoded destination coordinates for MVP.
 * Used as fallback when backend doesn't provide coordinates.
 *
 * Format: [longitude, latitude] (Mapbox convention)
 *
 * Post-MVP: Replace with backend geocoding service.
 */

const DESTINATION_COORDS: Record<string, [number, number]> = {
  // Southeast Asia
  bali: [115.1889, -8.4095],
  'bali, indonesia': [115.1889, -8.4095],
  bangkok: [100.5018, 13.7563],
  'bangkok, thailand': [100.5018, 13.7563],
  singapore: [103.8198, 1.3521],
  'ho chi minh city': [106.6297, 10.8231],
  hanoi: [105.8342, 21.0278],
  'kuala lumpur': [101.6869, 3.139],
  phuket: [98.3923, 7.8804],
  'chiang mai': [98.9853, 18.7883],

  // East Asia
  tokyo: [139.6917, 35.6895],
  'tokyo, japan': [139.6917, 35.6895],
  kyoto: [135.7681, 35.0116],
  osaka: [135.5023, 34.6937],
  seoul: [126.978, 37.5665],
  'hong kong': [114.1694, 22.3193],
  taipei: [121.5654, 25.033],
  beijing: [116.4074, 39.9042],
  shanghai: [121.4737, 31.2304],

  // Europe
  paris: [2.3522, 48.8566],
  'paris, france': [2.3522, 48.8566],
  london: [-0.1276, 51.5074],
  rome: [12.4964, 41.9028],
  barcelona: [2.1734, 41.3851],
  amsterdam: [4.9041, 52.3676],
  berlin: [13.405, 52.52],
  lisbon: [-9.1393, 38.7223],
  vienna: [16.3738, 48.2082],
  prague: [14.4378, 50.0755],
  athens: [23.7275, 37.9838],
  'santorini, greece': [25.4615, 36.3932],
  santorini: [25.4615, 36.3932],
  amalfi: [14.6028, 40.6334],
  'amalfi coast': [14.6028, 40.6334],
  florence: [11.2558, 43.7696],
  venice: [12.3155, 45.4408],
  nice: [7.262, 43.7102],
  'swiss alps': [8.2275, 46.8182],
  zermatt: [7.7486, 46.0207],

  // Americas
  'new york': [-74.006, 40.7128],
  'los angeles': [-118.2437, 34.0522],
  miami: [-80.1918, 25.7617],
  'san francisco': [-122.4194, 37.7749],
  cancun: [-86.8515, 21.1619],
  'mexico city': [-99.1332, 19.4326],
  'costa rica': [-84.0907, 9.7489],
  'buenos aires': [-58.3816, -34.6037],
  rio: [-43.1729, -22.9068],
  'rio de janeiro': [-43.1729, -22.9068],
  peru: [-77.0428, -12.0464],
  lima: [-77.0428, -12.0464],
  'machu picchu': [-72.545, -13.1631],

  // Island Destinations
  maldives: [73.2207, 3.2028],
  'maldives islands': [73.2207, 3.2028],
  fiji: [178.065, -17.7134],
  'bora bora': [-151.7415, -16.5004],
  hawaii: [-155.5828, 19.8968],
  maui: [-156.3319, 20.7984],
  seychelles: [55.492, -4.6796],
  mauritius: [57.5522, -20.3484],

  // Middle East & Africa
  dubai: [55.2708, 25.2048],
  'abu dhabi': [54.3773, 24.4539],
  marrakech: [-7.9811, 31.6295],
  'cape town': [18.4241, -33.9249],
  cairo: [31.2357, 30.0444],
  istanbul: [28.9784, 41.0082],
  'tel aviv': [34.7818, 32.0853],
  jerusalem: [35.2137, 31.7683],

  // Oceania
  sydney: [151.2093, -33.8688],
  melbourne: [144.9631, -37.8136],
  queenstown: [168.6626, -45.0312],
  'new zealand': [174.886, -40.9006],
  auckland: [174.7633, -36.8485],
};

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

/**
 * Get coordinates for a destination string.
 * Performs case-insensitive lookup with normalization.
 *
 * @param destination - Destination name (e.g., "Bali", "Paris, France")
 * @returns [longitude, latitude] tuple or null if not found
 */
export function getDestinationCoords(
  destination: string | null | undefined
): [number, number] | null {
  if (!destination) return null;

  const key = destination.toLowerCase().trim();

  // Direct match
  if (DESTINATION_COORDS[key]) {
    return DESTINATION_COORDS[key];
  }

  // Try without country suffix (e.g., "Bali, Indonesia" -> "bali")
  const withoutCountry = key.split(',')[0].trim();
  if (DESTINATION_COORDS[withoutCountry]) {
    return DESTINATION_COORDS[withoutCountry];
  }

  // Try partial match (first word)
  const firstWord = key.split(' ')[0];
  if (DESTINATION_COORDS[firstWord]) {
    return DESTINATION_COORDS[firstWord];
  }

  return null;
}
