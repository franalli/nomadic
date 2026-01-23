/**
 * Deterministic placeholder images for tiles and branches.
 * Same entity always gets the same image to avoid flicker.
 */

/**
 * Simple hash function for string to number.
 */
function hashCode(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash) + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

// Curated Unsplash photo IDs by category (high-quality travel imagery)
const PLACEHOLDER_IMAGES: Record<string, string[]> = {
  hotel: [
    'photo-1566073771259-6a8506099945',
    'photo-1551882547-ff40c63fe5fa',
    'photo-1564501049412-61c2a3083791',
    'photo-1520250497591-112f2f40a3f4',
  ],
  flight: [
    'photo-1436491865332-7a61a109cc05',
    'photo-1529074963764-98f45c47344b',
    'photo-1474302770737-173ee21bab63',
    'photo-1569629743817-70d8db6c323b',
  ],
  activity: [
    'photo-1527631746610-bca00a040d60',
    'photo-1501555088652-021faa106b9b',
    'photo-1551632811-561732d1e306',
    'photo-1506905925346-21bda4d32df4',
  ],
  destination: [
    'photo-1488646953014-85cb44e25828',
    'photo-1501785888041-af3ef285b470',
    'photo-1476514525535-07fb3b4ae5f1',
    'photo-1469474968028-56623f02e42e',
  ],
  default: [
    'photo-1488646953014-85cb44e25828',
    'photo-1469474968028-56623f02e42e',
    'photo-1506905925346-21bda4d32df4',
    'photo-1476514525535-07fb3b4ae5f1',
  ],
};

type TilePlaceholderInput = {
  id?: string;
  slug?: string;
  destination?: string;
  category?: string;
  type?: string;
};

/**
 * Get a deterministic placeholder image URL for a tile.
 * Same tile always gets the same image.
 */
export function placeholderImageForTile(tile: TilePlaceholderInput): string {
  const seed = tile.id || tile.slug || `${tile.destination}-${tile.category || tile.type}`;
  const hash = hashCode(seed);

  // Determine category from type
  let category = 'default';
  const type = (tile.type || tile.category || '').toLowerCase();
  if (type.includes('hotel') || type.includes('stay')) {
    category = 'hotel';
  } else if (type.includes('flight')) {
    category = 'flight';
  } else if (type.includes('activity') || type.includes('experience')) {
    category = 'activity';
  }

  const images = PLACEHOLDER_IMAGES[category] || PLACEHOLDER_IMAGES.default;
  const index = hash % images.length;
  return `https://images.unsplash.com/${images[index]}?w=400&h=300&fit=crop&auto=format`;
}

type BranchPlaceholderInput = {
  id?: string;
  destinations?: string[];
  index?: number;
};

/**
 * Get deterministic placeholder hero images for a branch.
 * Same branch always gets the same images.
 */
export function placeholderImagesForBranch(branch: BranchPlaceholderInput): string[] {
  const seed = branch.id || branch.destinations?.join(',') || `branch-${branch.index ?? 0}`;
  const hash = hashCode(seed);
  const images = PLACEHOLDER_IMAGES.destination;

  // Return 3 different images based on hash
  return [
    `https://images.unsplash.com/${images[hash % images.length]}?w=1600&h=900&fit=crop&auto=format`,
    `https://images.unsplash.com/${images[(hash + 1) % images.length]}?w=900&h=600&fit=crop&auto=format`,
    `https://images.unsplash.com/${images[(hash + 2) % images.length]}?w=900&h=600&fit=crop&auto=format`,
  ];
}
