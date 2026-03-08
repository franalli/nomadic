/**
 * Render a numeric rating as repeated star characters.
 * Clamps to 0-5 stars.
 */
export function renderStarRating(rating: number): string {
  const stars = Math.round(rating);
  return '\u2605'.repeat(Math.min(stars, 5));
}
