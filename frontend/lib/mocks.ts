/**
 * Mock data for branch and tile display.
 *
 * @deprecated This entire file should be removed once real metadata is available from the API.
 *
 * ## Migration Plan
 *
 * ### Backend Changes Required
 * 1. Add to Branch schema: `vibe: str`, `highlights: list[str]`, `flow: list[str]`, `notes: list[str]`
 * 2. Add to Tile schema: `meta.features: list[str]`
 * 3. Populate these fields in the plan generation endpoint
 *
 * ### Frontend Migration Steps
 * 1. Update components to check for API data first: `branch.vibe ?? DETAIL_PRESETS[index].vibe`
 * 2. Once backend provides data consistently, remove fallback to mocks
 * 3. Delete this file and update imports
 *
 * ### Removal Triggers
 * - DETAIL_PRESETS: Remove when API provides Branch.vibe, Branch.highlights, Branch.flow, Branch.notes
 * - HOTEL/FLIGHT/ACTIVITY_FEATURE_SETS: Remove when API provides Tile.meta.features: string[]
 *
 * These hardcoded presets with stock Unsplash images are placeholders until
 * the backend provides actual branch details (vibe, highlights, flow, notes).
 */

// Development warning - helps track when this deprecated code is still in use
if (process.env.NODE_ENV === 'development') {
  console.warn(
    '[DEPRECATED] lib/mocks.ts is loaded. See file header for migration plan to remove mock data.'
  );
}

export type BranchDetails = {
  vibe: string;
  duration: string;
  budget: string;
  focus: string;
  heroImages: string[];
  highlights: string[];
  flow: string[];
  notes: string[];
};

/**
 * Preset branch details for display when real metadata isn't available.
 * Cycled through based on branch index.
 */
export const DETAIL_PRESETS: BranchDetails[] = [
  {
    vibe: 'Coastal hikes + harbor nights',
    duration: '5-7 days',
    budget: '$$ to $$$',
    focus: 'Sea cliffs, seafood, slower mornings',
    heroImages: [
      'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1600&q=80',
      'https://images.unsplash.com/photo-1505761671935-60b3a7427bad?auto=format&fit=crop&w=900&q=80',
      'https://images.unsplash.com/photo-1476610182048-b716b8518aae?auto=format&fit=crop&w=900&q=80',
    ],
    highlights: [
      'Cliff walk sunrise above {destination}',
      'Seafood tastings and harbor-side cafes',
      'Hidden coves for late-afternoon swims',
    ],
    flow: [
      'Day 1-2: Settle in, coastal trail, market dinner with ocean views',
      'Day 3-4: Island-hop by boat, snorkel bays, sunset sail back',
      'Day 5+: Bike shoreline villages, picnic on quieter beaches',
    ],
    notes: [
      'Pack layers — breezy nights near the water',
      'Book small boats 24h ahead in peak season',
      'Carry small cash for seaside cafes and bakeries',
    ],
  },
  {
    vibe: 'Alpine lakes + ridgeline views',
    duration: '6-9 days',
    budget: '$$',
    focus: 'Hikes, hut-to-hut stays, glacier viewpoints',
    heroImages: [
      'https://images.unsplash.com/photo-1501785888041-af3ef285b470?auto=format&fit=crop&w=1600&q=80',
      'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=900&q=80',
      'https://images.unsplash.com/photo-1489515217757-5fd1be406fef?auto=format&fit=crop&w=900&q=80',
    ],
    highlights: [
      'Ridgeline hike above {destination} with alpine lakes',
      'Cable car to glacier terrace at golden hour',
      'Hut dinner with local cheese and mountain herbs',
    ],
    flow: [
      'Day 1-2: Warm-up lake loops, cable car summit, spa evening',
      'Day 3-5: Two-night hut circuit with panoramic ridges',
      'Day 6+: Slow day in valley villages, farm-to-table tasting',
    ],
    notes: [
      'Reserve huts 2-3 weeks out for best dorms',
      'Weather flips fast — light shell + microspikes recommended',
      'Transit pass covers lifts and valley buses',
    ],
  },
  {
    vibe: 'Design-forward city break',
    duration: '4-6 days',
    budget: '$$ to $$$',
    focus: 'Boutique stays, galleries, night markets',
    heroImages: [
      'https://images.unsplash.com/photo-1467269204594-9661b134dd2b?auto=format&fit=crop&w=1600&q=80',
      'https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=900&q=80',
      'https://images.unsplash.com/photo-1440404653325-ab127d49abb4?auto=format&fit=crop&w=900&q=80',
    ],
    highlights: [
      'Neighborhood coffee crawl across {destination}',
      'Evening street food and design market stop',
      'Modern art wing + rooftop aperitivo',
    ],
    flow: [
      'Day 1: Settle into boutique stay, sunset walk through old town',
      'Day 2-3: Gallery hop, chef-led dinner, night market shopping',
      'Day 4+: Day trip to nearby coast/vineyards, late train back',
    ],
    notes: [
      'Prebook timed gallery entries on weekends',
      'Most cafes cashless; markets prefer small notes',
      'Ride share + metro combo is fastest across districts',
    ],
  },
  {
    vibe: 'Desert canyons + stargazing',
    duration: '5-8 days',
    budget: '$ to $$',
    focus: 'Red rock vistas, slot canyons, campfire nights',
    heroImages: [
      'https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1600&q=80',
      'https://images.unsplash.com/photo-1500534314209-a25ddb2bd429?auto=format&fit=crop&w=900&q=80',
      'https://images.unsplash.com/photo-1501004318641-b39e6451bec6?auto=format&fit=crop&w=900&q=80',
    ],
    highlights: [
      'Slot canyon walk at sunrise outside {destination}',
      '4x4 trail to overlook for sunset charcuterie',
      'Stargazing pad with hot chocolate under clear skies',
    ],
    flow: [
      'Day 1-2: Canyon rim hikes, settle into casita or camp',
      'Day 3-4: Guided slot canyon + night sky session',
      'Day 5+: Scenic byway drive, desert hot springs wind-down',
    ],
    notes: [
      'Hydrate constantly — dry air sneaks up fast',
      'Permits required for some canyon slots — secure early',
      'Cool nights — pack a light puffer even in summer',
    ],
  },
];

/**
 * Mock feature sets for tiles when real metadata isn't available.
 *
 * @deprecated Remove these exports when API provides `Tile.meta.features: string[]`.
 * Check TileCard.tsx getFeaturesForTile() which consumes these.
 */
export const HOTEL_FEATURE_SETS = [
  ['Free WiFi', 'Breakfast Included', 'Rooftop Bar'],
  ['Pool', 'Spa', 'Restaurant'],
  ['Historic Building', 'City Views', 'Concierge'],
  ['Gym', 'Room Service', 'Bar'],
];

export const FLIGHT_FEATURE_SETS = [
  ['Carry-on included', 'Meal included', 'USB Power'],
  ['Free cancellation', 'Seat selection', 'Wifi on board'],
  ['Priority boarding', 'Extra legroom', 'Lounge access'],
];

export const ACTIVITY_FEATURE_SETS = [
  ['Small group', 'Guide included', 'Skip the line'],
  ['Private tour', 'Hotel pickup', 'Mobile ticket'],
  ['Instant confirmation', 'Free cancellation', 'English guide'],
];
