import type { ActivityColorEntry } from '@/hooks/useActivityColorMap';

// Matches markdown links: [text](url)
const MARKDOWN_LINK_RE = /\[(?:[^\]]*)\]\([^)]*\)/g;

/**
 * Split text into segments: markdown links (protected) vs plain text.
 */
function splitByLinks(text: string): { text: string; isLink: boolean }[] {
  const segments: { text: string; isLink: boolean }[] = [];
  let lastIndex = 0;

  MARKDOWN_LINK_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = MARKDOWN_LINK_RE.exec(text)) !== null) {
    if (match.index > lastIndex) {
      segments.push({ text: text.slice(lastIndex, match.index), isLink: false });
    }
    segments.push({ text: match[0], isLink: true });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) {
    segments.push({ text: text.slice(lastIndex), isLink: false });
  }

  return segments;
}

/**
 * Pre-process markdown content to wrap known activity names in
 * special activity-color: protocol links for colored rendering.
 *
 * Uses longest-match-first to avoid partial matches.
 * Word boundaries (\b) prevent "Via" matching inside "Trivia".
 * Re-splits after each pattern to protect newly created links
 * from corruption by subsequent shorter patterns.
 */
export function highlightActivityNames(
  content: string,
  colorMap: ActivityColorEntry[],
): string {
  if (!colorMap.length) return content;

  let result = content;

  for (const entry of colorMap) {
    const escaped = entry.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`\\b(${escaped})\\b`, 'gi');

    // Split into link-protected vs plain-text segments
    const segments = splitByLinks(result);

    // Replace only in plain-text segments
    let changed = false;
    for (const seg of segments) {
      if (seg.isLink) continue;
      const replaced = seg.text.replace(regex, `[$1](actcolor:${entry.specialistType})`);
      if (replaced !== seg.text) {
        seg.text = replaced;
        changed = true;
      }
    }

    if (changed) {
      result = segments.map((s) => s.text).join('');
    }
  }

  return result;
}
