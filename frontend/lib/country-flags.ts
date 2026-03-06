/**
 * Convert ISO 3166-1 alpha-2 country code to flag emoji.
 * Algorithmic -- works for ALL countries, no lookup table.
 * Each letter is offset into the Regional Indicator Symbol range (U+1F1E6..U+1F1FF).
 *
 * "US" -> flag_US, "JP" -> flag_JP, "ID" -> flag_ID
 *
 * Returns globe emoji for invalid/missing codes.
 */
export function countryCodeToFlag(code: string | null | undefined): string {
  if (!code || code.length !== 2) return '\u{1F30D}';
  const upper = code.toUpperCase();
  return String.fromCodePoint(
    ...[...upper].map(c => 0x1F1E6 + c.charCodeAt(0) - 65)
  );
}
