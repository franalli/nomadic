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
  culture: [
    'photo-1493976040374-85c8e12f0c0e',
    'photo-1518998053901-5348d3961a04',
    'photo-1552832230-c0197dd311b5',
    'photo-1504598318550-17eba1008a68',
  ],
  cooking: [
    'photo-1556910103-1c02745aae4d',
    'photo-1507048331197-7d4ac70811cf',
    'photo-1466637574441-749b8f19452f',
    'photo-1414235077428-338989a2e8c0',
  ],
  wellness: [
    'photo-1540555700478-4be289fbec6d',
    'photo-1544161515-4ab6ce6db874',
    'photo-1600334089648-b0d9d3028eb2',
    'photo-1515377905703-c4788e51af15',
  ],
  nightlife: [
    'photo-1566417713940-fe7c737a9ef2',
    'photo-1514933651103-005eec06c04b',
    'photo-1470337458703-46ad1756a187',
    'photo-1516450360452-9312f5e86fc7',
  ],
  hiking: [
    'photo-1551632811-561732d1e306',
    'photo-1506905925346-21bda4d32df4',
    'photo-1464822759023-fed622ff2c3b',
    'photo-1527631746610-bca00a040d60',
  ],
  skiing: [
    'photo-1551524559-8af4e6624178',
    'photo-1605540436563-5bca919ae766',
    'photo-1517483000871-1dbf64a6e1c6',
    'photo-1516939884455-1445c8652f83',
  ],
  diving: [
    'photo-1544551763-46a013bb70d5',
    'photo-1559827260-dc66d52bef19',
    'photo-1544551763-77ef2d0cfc6c',
    'photo-1560275619-4662e36fa65c',
  ],
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

function activityPlaceholderCategory(rawCategory?: string): string {
  const key = (rawCategory || '').toLowerCase().trim();
  if (!key) return 'activity';

  if (/(culture|cultural|museum|landmark|monument|gallery|temple|church|mosque|synagogue|historic|plaza|ruins|fountain|attraction|point_of_interest|tour)/.test(key)) {
    return 'culture';
  }
  if (/(food|restaurant|cafe|bar|bakery|meal|cooking)/.test(key)) {
    return 'cooking';
  }
  if (/(nightlife|night|club)/.test(key)) {
    return 'nightlife';
  }
  if (/(spa|wellness|beauty|gym|massage|yoga)/.test(key)) {
    return 'wellness';
  }
  if (/(hike|trail|mountain|trek)/.test(key)) {
    return 'hiking';
  }
  if (/(ski|snow)/.test(key)) {
    return 'skiing';
  }
  if (/(dive|snorkel|reef|scuba)/.test(key)) {
    return 'diving';
  }
  if (/(nature|park|garden|zoo|beach|camp|adventure)/.test(key)) {
    return 'activity';
  }
  return 'activity';
}

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
    category = activityPlaceholderCategory(tile.category || tile.type);
  } else if (tile.category) {
    category = activityPlaceholderCategory(tile.category);
  }

  const images = PLACEHOLDER_IMAGES[category] || PLACEHOLDER_IMAGES.default;
  const index = hash % images.length;
  return `https://images.unsplash.com/${images[index]}?w=400&h=300&fit=crop&auto=format`;
}

type BranchPlaceholderInput = {
  id?: string;
  destination?: string | null;
  index?: number;
};

/**
 * Get deterministic placeholder hero images for a branch.
 * Same branch always gets the same images.
 */
export function placeholderImagesForBranch(branch: BranchPlaceholderInput): string[] {
  const seed = branch.id || branch.destination || `branch-${branch.index ?? 0}`;
  const hash = hashCode(seed);
  const images = PLACEHOLDER_IMAGES.destination;

  // Return 3 different images based on hash
  return [
    `https://images.unsplash.com/${images[hash % images.length]}?w=1600&h=900&fit=crop&auto=format`,
    `https://images.unsplash.com/${images[(hash + 1) % images.length]}?w=900&h=600&fit=crop&auto=format`,
    `https://images.unsplash.com/${images[(hash + 2) % images.length]}?w=900&h=600&fit=crop&auto=format`,
  ];
}
