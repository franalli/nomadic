'use client';

import { useMemo } from 'react';
import { useShallow } from 'zustand/react/shallow';

import { getSpecialistColor } from '@/lib/specialists';
import { useDocumentStore } from '@/state/documentStore';
import type { Tile } from '@/types/tile';

export type ActivityColorEntry = {
  name: string;
  specialistType: string;
  color: string;
};

// Default color is zinc — skip entries that would be invisible against chat text
const DEFAULT_COLOR = getSpecialistColor(undefined);

// Common suffixes on tile/block titles that aren't part of the place name
const TITLE_SUFFIX_RE = /\s+(?:Walking Tour|Day Trip|Exploration|Experience|Excursion|Adventure|Workshop|Class|Lesson|Session|Visit|Tour|Trip)$/i;

/**
 * Extract matchable name fragments from a tile/block title.
 * "Colosseum and Roman Forum Tour" → ["Colosseum and Roman Forum Tour", "Colosseum", "Roman Forum"]
 * "Vatican Museums, Sistine Chapel, and St. Peter's Basilica Tour"
 *   → [full, "Vatican Museums", "Sistine Chapel", "St. Peter's Basilica"]
 */
function extractMatchableNames(title: string): string[] {
  const names: string[] = [title];

  // Split by ", " and " and " to extract parts
  const parts = title.split(/,\s+|\s+and\s+/i);
  if (parts.length <= 1) {
    // Single-part title — still strip suffix for a shorter match
    const stripped = title.replace(TITLE_SUFFIX_RE, '').trim();
    if (stripped.length >= 4 && stripped !== title) names.push(stripped);
    return names;
  }

  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed || trimmed.length < 4) continue;
    // Strip common activity suffixes
    const stripped = trimmed.replace(TITLE_SUFFIX_RE, '').trim();
    if (stripped.length >= 4) names.push(stripped);
    // Also add unstripped if different and long enough
    if (trimmed !== stripped && trimmed.length >= 4) names.push(trimmed);
  }

  return names;
}

/** Resolve a visible category from a tile's metadata chain. */
function resolveTileCategory(tile: Tile): string | null {
  if (tile.source_agent && getSpecialistColor(tile.source_agent) !== DEFAULT_COLOR) {
    return tile.source_agent;
  }
  const meta = tile.meta as Record<string, unknown> | undefined;
  if (!meta) return null;
  for (const key of ['map_type', 'browse_category', 'category']) {
    const val = meta[key];
    if (typeof val === 'string' && getSpecialistColor(val) !== DEFAULT_COLOR) return val;
  }
  return null;
}

/**
 * Builds a map of activity_name → category color from current plan state.
 * Sources (priority order): tiles, day_card blocks, strategy_sections content_added.
 * Extracts matchable name fragments from long titles (e.g., "Colosseum" from
 * "Colosseum and Roman Forum Tour") so the LLM's natural-language mentions match.
 * Sorted by name length DESC for longest-match-first greedy matching.
 *
 * Derived from current plan state (pure, render-safe).
 */
export function useActivityColorMap(): ActivityColorEntry[] {
  const { tiles, dayCards, sections } = useDocumentStore(
    useShallow((s) => ({
      tiles: s.document?.tiles,
      dayCards: s.document?.day_cards,
      sections: s.document?.strategy_sections,
    }))
  );

  return useMemo(() => {
    const seen = new Map<string, ActivityColorEntry>();

    function addEntry(name: string, category: string) {
      const color = getSpecialistColor(category);
      if (color === DEFAULT_COLOR) return;
      const key = name.toLowerCase();
      if (key.length < 4 || seen.has(key)) return;
      seen.set(key, { name, specialistType: category, color });
    }

    // Source 1: activity tiles (best source — titles match LLM chat text)
    if (tiles) {
      for (const tile of Object.values(tiles)) {
        if (tile.type !== 'activity' || !tile.title) continue;
        const cat = resolveTileCategory(tile);
        if (!cat) continue;
        for (const name of extractMatchableNames(tile.title)) {
          addEntry(name, cat);
        }
      }
    }

    // Source 2: day_card blocks (placed activities)
    for (const dc of dayCards ?? []) {
      for (const block of dc.blocks ?? []) {
        if (!block.summary) continue;
        const cat = block.map_type || block.specialist_type;
        if (!cat) continue;
        for (const name of extractMatchableNames(block.summary)) {
          addEntry(name, cat);
        }
      }
    }

    // Source 3: strategy_sections content_added (unplaced activities)
    // Prefer item.type (e.g. "attraction", "dining") over section specialist_type
    // so local_expert items get semantic colors instead of the near-default grey.
    for (const sec of sections ?? []) {
      for (const item of sec.content_added ?? []) {
        if (!item.title) continue;
        const cat = item.type || sec.specialist_type;
        if (cat) addEntry(item.title, cat);
      }
    }

    // Sort longest-first for greedy matching
    return Array.from(seen.values()).sort(
      (a, b) => b.name.length - a.name.length
    );
  }, [tiles, dayCards, sections]);
}
