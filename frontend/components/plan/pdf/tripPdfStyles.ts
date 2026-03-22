import { StyleSheet } from '@react-pdf/renderer';

// ---------------------------------------------------------------------------
// Monochrome palette — @react-pdf/renderer uses its own StyleSheet,
// not Tailwind/DS tokens. Only black/grey values; zero color in the PDF.
//
// IMPORTANT: Never use textTransform in @react-pdf/renderer — it interacts
// badly with letterSpacing, inserting spaces inside words. Always use
// .toUpperCase() in JS. Never use unicode symbols (emoji, etc.) — Helvetica
// doesn't have those glyphs and they render as garbage.
// ---------------------------------------------------------------------------

export const BLACK = '#18181b';     // zinc-900 — titles, names, headings
export const MID = '#71717a';       // zinc-500 — labels, metadata, constraints
export const LIGHT = '#a1a1aa';     // zinc-400 — period labels, intensity, footer
export const DARK_GREY = '#52525b'; // zinc-600 — underlined link text
export const RULE = '#d4d4d8';      // zinc-300 — horizontal rules

// ---------------------------------------------------------------------------
// Styles — no textTransform anywhere, no letterSpacing > 1
// ---------------------------------------------------------------------------

export const s = StyleSheet.create({
  // Page
  page: {
    padding: 40,
    fontFamily: 'Helvetica',
    fontSize: 10,
    color: BLACK,
  },
  footer: {
    position: 'absolute',
    bottom: 30,
    left: 40,
    right: 40,
    textAlign: 'center',
    fontSize: 7,
    color: LIGHT,
  },

  // Header
  brand: {
    fontSize: 8,
    letterSpacing: 1,
    color: MID,
    marginBottom: 8,
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
  },
  subtitle: {
    fontSize: 10,
    color: MID,
    marginTop: 3,
    marginBottom: 12,
  },
  rule: {
    borderBottomWidth: 1,
    borderBottomColor: RULE,
    marginBottom: 14,
  },

  // Days
  dayHeader: {
    fontSize: 10,
    fontWeight: 'bold',
    letterSpacing: 1,
    marginTop: 14,
  },
  dayMeta: {
    fontSize: 8,
    color: LIGHT,
    marginBottom: 6,
  },
  dashedRule: {
    borderBottomWidth: 0.5,
    borderBottomColor: RULE,
    borderBottomStyle: 'dashed',
    marginTop: 10,
    marginBottom: 10,
  },

  // Blocks
  blockWrap: {
    marginBottom: 8,
  },
  periodLabel: {
    fontSize: 7,
    letterSpacing: 0.5,
    color: LIGHT,
    marginBottom: 1,
  },
  specialistLabel: {
    fontSize: 7,
    fontWeight: 'bold',
    letterSpacing: 1,
    color: MID,
    marginBottom: 1,
  },
  blockName: {
    fontSize: 11,
    fontWeight: 'bold',
    marginBottom: 1,
  },
  blockMeta: {
    fontSize: 9,
    color: MID,
    marginBottom: 2,
  },
  constraintInline: {
    fontSize: 8,
    color: MID,
    paddingLeft: 8,
    fontStyle: 'italic',
    marginBottom: 6,
  },
  bufferWrap: {
    marginBottom: 4,
  },
  bufferBlock: {
    fontSize: 10,
    color: MID,
    fontStyle: 'italic',
    marginBottom: 6,
  },

  // Venue Links
  venueLinksWrap: {
    marginTop: 16,
  },
  sectionTitle: {
    fontSize: 9,
    fontWeight: 'bold',
    letterSpacing: 1,
    marginTop: 16,
    marginBottom: 8,
  },
  linksSubHeader: {
    fontSize: 10,
    fontWeight: 'bold',
    marginBottom: 4,
    marginTop: 8,
  },
  venueRow: {
    marginBottom: 8,
  },
  venueNameRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  venueName: {
    fontSize: 10,
    fontWeight: 'bold',
  },
  venueDetail: {
    fontSize: 9,
    color: MID,
  },
  venueLink: {
    fontSize: 7,
    color: DARK_GREY,
    textDecoration: 'underline',
    marginBottom: 8,
  },
});

/** Clean duration: "4.0h" -> "4h", "6.0h" -> "6h" */
export function cleanDuration(d: string | null): string | null {
  if (!d) return null;
  return d.replace(/\.0h$/, 'h');
}
