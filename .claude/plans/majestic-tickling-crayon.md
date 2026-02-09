# Stage 3H: Frontend Specialist Constants Migration

## Context

The frontend has ~15 files with hardcoded specialist arrays, color maps, keyword dicts, and icon lookups. Adding a specialist means editing all of them. This migration consolidates everything into `frontend/lib/specialists.ts` so adding a specialist = 1 registry entry + 1 backend prompt file.

Ships after backend Stage 3A-3G is verified on `backend_refactor` branch.

---

## Spec vs Reality — Key Discrepancies

| Spec item | Reality | Resolution |
|-----------|---------|------------|
| H3: "No change needed" | `S2StrategyView.tsx` has `TOPIC_PRIORITY` array (line 98) AND `TOPIC_CONFIG` object (lines 101-150) with hardcoded specialist names, icons, labels, and action strings | **Migrate both** — import icon/label from registry, update TOPIC_PRIORITY to include new specialists |
| H10: `.specialist-*` CSS classes | Actually CSS custom properties: `--topic-diving`, `--topic-hiking`, etc. (globals.css lines 65-72) used by data-topic selectors | **Update** to add new specialists + rename boating→sailing. NOT dead CSS. |
| H11: "Activity category pills" | `TripDetailsForm.tsx` has `ACTIVITY_ICONS` — a general activity→icon mapper (hiking, trekking, diving, scuba, surfing, skiing, boating, sailing, etc.). NOT specialist-specific. | **Skip** — this maps ~30 activity categories to icons, not specialist types |
| H12: "Chat state machine" | No separate state machine file. Specialist types handled in `specialistLinkParser.ts` (already H9) | **Covered by H9** |
| H13: "API types union" | `specialist_type` is already `string` in `plan-envelope.ts`, not a literal union | **No change needed** |
| H14: "Map pin colors" | `InteractiveMap.tsx` lines 188-216: `getMarkerIcon()` and `getMarkerColor()` match activity text (not specialist_type). `MapLayerFilter.tsx` lines 45-55: `LAYER_CONFIG` has diving/hiking entries | **Migrate MapLayerFilter** (specialist-typed). **Skip InteractiveMap** (activity-text matching, different concern) |
| H15: "Landing page" | No landing page with specialist showcase exists | **Skip** |
| Not in spec | `specialist-utils.ts` — `getActiveSpecialists()` filters out 'general'/'local_expert' | **Import `SPECIALIST_IDS` for validation** |
| Not in spec | `S2StrategyView.tsx` — `TOPIC_CONFIG` with readyAction/updatingAction strings per specialist | **Keep local** to S2StrategyView with `??` default fallback |

---

## H0: Create `frontend/lib/specialists.ts` (~120 lines)

New file. Single source of truth.

```
SpecialistConfig {
  id, displayName, icon (Lucide name string), emoji, color (hex),
  filterKeywords[]
}
```

**Registry**: 8 entries (diving, hiking, skiing, cycling, surfing, climbing, sailing, wildlife_safari)

**Derived exports**:
- `SPECIALIST_IDS` — all Tier 1 IDs
- `NICHE_SPECIALIST_IDS` — same (alias for clarity)
- `SPECIALIST_COLORS` — Record with backward-compat aliases (boating→sailing, local_expert, general, default)
- `getSpecialistColor(type?)` — hex with fallback
- `getSpecialistConfig(type?)` — config with boating→sailing compat
- `activityMatchesSpecialist(tile, specialistTypes)` — keyword filter
- `SPECIALIST_DISPLAY_NAMES` — for regex generation in link parser

---

## Migration Steps (13 files, executed in order)

### H1: `components/plan/timeline/blocks/types.ts`
- **Delete**: `TOPIC_COLORS` (lines 54-62), `SPECIALIST_COLORS` (lines 68-76), `getSpecialistBorderColor()`, `getTopicColor()`
- **Import**: `getSpecialistColor` from `lib/specialists`
- Call sites use `style={{ borderLeftColor: getSpecialistColor(type) }}` — no Tailwind class names, no hex→name reverse lookup

### H2: `components/plan/StrategyStageRenderer.tsx`
- **Delete**: `NICHE_SPECIALISTS` array (line 886)
- **Import**: `NICHE_SPECIALIST_IDS` from `lib/specialists`
- **Update**: `getAlternativeDestinations()` switch (lines 173-188) — keep local, add climbing/sailing/wildlife_safari cases with `default: 'Try a different destination.'` fallback. UI copy, same category as readyAction strings.

### H3: `components/plan/stages/S2StrategyView.tsx`
- **Update**: `TOPIC_PRIORITY` (line 98) — add new specialists before 'general'
- **Update**: `TOPIC_CONFIG` (lines 101-150) — import icon/label from registry, keep readyAction/updatingAction local with `?? DEFAULT_CONFIG` fallback

### H4: `components/plan/stages/StrategyHero.tsx`
- **Delete**: `TOPIC_CONFIG` (lines 42-56), `SPECIALIST_COLORS` (lines 77-85)
- **Update**: `FALLBACK_IMAGES` — add entries for climbing, sailing, wildlife_safari (or move to registry)
- **Update**: `getConstraintSectionLabel()` (lines 103-114) — add new specialists
- **Import**: `getSpecialistConfig` from `lib/specialists`

### H5: `components/plan/SelectionsBar.tsx`
- **Delete**: `SPECIALIST_KEYWORDS` (lines 105-112), `activityMatchesSpecialist()` (lines 115-137)
- **Import**: `activityMatchesSpecialist` from `lib/specialists`
- **Keep**: `detectSpecialistType()` if still needed, or move to registry

### H6: `components/plan/BookingSection.tsx`
- **Delete**: `SPECIALIST_KEYWORDS` (lines 51-58), `activityMatchesSpecialist()` (lines 65-88)
- **Import**: `activityMatchesSpecialist` from `lib/specialists`

### H7: `frontend/lib/loaderConfig.ts`
- **Replace**: Hardcoded `*_specialist` entries in `LOADER_ETA_THRESHOLDS` and `ACTION_TYPE_NODE_MAP` with dynamic generation from `SPECIALIST_IDS`

### H8: `components/chat/TripStatusBar.tsx`
- **Delete**: `SPECIALIST_EMOJI` (lines 26-33)
- **Import**: `getSpecialistConfig` from `lib/specialists`, use `.emoji`

### H9: `frontend/lib/specialistLinkParser.ts`
- **Delete**: `SpecialistType` union (lines 13-20), `SPECIALIST_PATTERNS` regex (lines 30-35), `getSpecialistDisplayName()` (lines 108-119)
- **Rewrite**: Generate regex from `SPECIALIST_IDS` + display names dynamically
- **Import**: `SPECIALIST_IDS`, `getSpecialistConfig` from `lib/specialists`

### H10: `frontend/app/globals.css`
- **Update**: CSS custom properties (lines 65-72) — add `--topic-climbing`, `--topic-sailing`, `--topic-wildlife-safari`
- **Rename**: `--topic-boating` → `--topic-sailing` (keep boating as alias if referenced)
- **Add**: `--topic-surfing` (currently missing!)

### H11: `frontend/lib/specialist-utils.ts`
- **Update**: `getActiveSpecialists()` — import `SPECIALIST_IDS` and use `.includes()` instead of hardcoded !== checks (future-proof)

### H12: `components/map/MapLayerFilter.tsx`
- **Update**: `LAYER_CONFIG` diving/hiking entries — import icon/label/color from registry

### H13: `components/map/InteractiveMap.tsx`
- **Skip for now** — `getMarkerIcon()` and `getMarkerColor()` match on activity text strings (not specialist_type), a different concern

---

## Files NOT Changed (confirmed)

| File | Reason |
|------|--------|
| `TripDetailsForm.tsx` | General activity→icon mapper (~30 categories), not specialist-typed |
| `InteractiveMap.tsx` | Activity text matching, not specialist_type |
| `plan-envelope.ts` | `specialist_type` already typed as `string` |
| No landing page | Doesn't exist |

---

## Execution Order & File Count

```
H0  → lib/specialists.ts              (NEW — 1 file)
H1  → timeline/blocks/types.ts        (edit)
H5  → SelectionsBar.tsx               (edit)
H6  → BookingSection.tsx              (edit)
H8  → TripStatusBar.tsx               (edit)
H9  → specialistLinkParser.ts         (edit)
H11 → specialist-utils.ts             (edit)
H7  → loaderConfig.ts                 (edit)
H2  → StrategyStageRenderer.tsx       (edit)
H3  → S2StrategyView.tsx              (edit)
H4  → StrategyHero.tsx                (edit)
H10 → globals.css                     (edit)
H12 → MapLayerFilter.tsx              (edit)
```

**Total: 13 files** (1 new + 12 edits). 5-file limit waived for this task.

UI-specific metadata stays local:
- `readyAction`/`updatingAction` strings → local to S2StrategyView
- `FALLBACK_IMAGES` → local to StrategyHero
- `getConstraintSectionLabel()` → local to StrategyHero
Each gets a generic default fallback for unknown specialist types.

`npm run build` verified after every 2-3 steps.

---

## Verification

1. `npm run build` — zero errors
2. `npm run lint` — no unused imports, no lint errors
3. Visual spot-checks:
   - Existing specialists render with correct colors, icons, emojis
   - Trip DNA bar shows niche specialists (no local_expert/general)
   - Activity filtering works (diving tiles shown for diving, hidden for cycling)
   - Backward compat: `specialist_type: "boating"` renders as sailing color/icon
4. New specialists:
   - `specialist_type: "climbing"` → orange border, correct icon
   - `specialist_type: "wildlife_safari"` → amber border, correct icon
   - Unknown type → zinc fallback, no crash
5. Chat link parser detects all 8 specialist names in bold mentions
