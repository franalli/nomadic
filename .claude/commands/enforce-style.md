Audit every UI component for visual consistency against `docs/design-system.md`.
**Full component scan. Not diff-driven.** Read every `.tsx` component file and verify its styling.
**This command FIXES code to match the spec, and EXTENDS the spec for undocumented elements.**

---

## Phase 0: Load the Spec

Read these files fully before starting:

1. `docs/design-system.md` — the style SSoT (all color, spacing, contrast, typography rules live here)
2. `frontend/lib/design-system.ts` — the `DS` token object
3. `frontend/tailwind.config.mts` — custom overrides (shadows, rounded-lg, colors)
4. `frontend/lib/specialists.ts` — specialist color registry

Keep them in context throughout. Every check below references sections in `docs/design-system.md` by number. If a section number has shifted, locate it by heading name.

---

## Phase 1: DS Token Compliance

For EACH `.tsx` file in `frontend/components/`:

### 1A: Raw Tailwind vs DS Token

Cross-reference each component's Tailwind classes against the DS tokens in **Section 2 (Design Tokens Reference)** of `design-system.md`. If a component uses raw Tailwind that matches a DS token's light+dark value (materials, actions, pills, text, stepper, infoBox), flag it.

**Exception:** Components in the **Section 6 (Component Mapping)** table documented as using "raw patterns" matching DS values are acceptable. Note them but don't flag.

**Exception:** `ui/` primitives (button.tsx, card.tsx, sheet.tsx, skeleton.tsx, switch.tsx, tooltip.tsx, popover.tsx) may use their own token systems (shadcn). Skip unless they conflict with DS values.

### 1B: Missing Dark Mode

For each component, check that every color/background/border class has a `dark:` counterpart. The correct dark-mode pairings are defined in:

- **Section 2 (Design Tokens)** — each token table has Light and Dark columns
- **Section 4 (Color Rules Summary)** — Light Mode Palette and Dark Mode Palette tables
- **Section 17.7 (Text-on-Background Contrast)** — Known-Good Pairs tables

Flag every color class missing its `dark:` pair. This is the most common consistency issue.

**Exception:** Classes inside `dark:` conditionals or components that only render in one mode.

### 1C: Missing Mobile Responsiveness

Check for desktop-only patterns missing mobile variants. Reference:

- **Section 17.6 (Spacing Standard)** — Desktop vs Mobile Spacing Scale table
- **Touch Targets section** — minimum hit areas for mobile elements
- **Sticky Panels section (2.5)** — desktop vs mobile map/content layout

Flag fixed widths, large text, or wide padding without a responsive override or `useIsDesktop` gate.

**Exception:** Components gated by `useIsDesktop` or mobile layout branching.

---

## Phase 2: Color & Spacing Consistency

### 2A: Restricted Color Violations

Search for banned or restricted color usage per **Section 4 (Color Rules — Restricted Colors)**.

```bash
# Banned: teal
grep -rn "teal" frontend/components/ --include="*.tsx"

# Restricted: amber/orange
grep -rn "amber\|orange\|#E86A1F\|#F59E0B" frontend/components/ --include="*.tsx"
```

For each amber/orange hit, verify it falls into an approved category listed in the Restricted Colors table. Anything else is a violation.

### 2B: Emerald Consistency

Verify emerald shade usage matches the spec. Cross-reference each `emerald-*` occurrence against:

- **Section 2 (Actions)** — primary action dark mode shade
- **Section 2 (Actions)** — toggle on shade
- **Section 2.5 (Heart Preference)** — pressed heart shade
- **Section 7 (Calendar)** — caps and today text shades
- **Section 2 (Typography)** — text accent shade

```bash
grep -rn "emerald" frontend/components/ --include="*.tsx"
```

### 2C: Zinc Scale Consistency

Verify zinc shade assignments follow **Section 4 (Color Rules — Light Mode Palette / Dark Mode Palette)**. Flag inversions (e.g., `zinc-400` for primary text in light mode, `zinc-200` for text).

### 2D: Text-on-Background Contrast

For EVERY text element, verify font color vs resolved background passes the rules in **Section 17.7 (Text-on-Background Contrast)**:

1. Check the pair against the **Known-Good Pairs** tables (light and dark)
2. Check against the **Failing Pairs** table
3. Apply the **Evaluation Rules** (spec wins, check both modes, trace inheritance, semi-transparent bg handling, placeholder text, disabled exemption)

For every text-rendering element (`<p>`, `<span>`, `<h1>`–`<h6>`, `<label>`, `<button>` text, `<input>` placeholder):
1. Identify the text color class
2. Identify the background it sits on (own `bg-*` or nearest ancestor)
3. If the pair fails, fix it per the Failing Pairs table's "Correct Alternative" column

### 2E: Spacing, Padding & Margin Consistency

For EVERY component, verify spacing follows **Section 17.6 (Spacing Standard)**:

1. **Tier compliance** — all gap/padding/margin values snap to Within/Between/Major tiers (or listed exceptions)
2. **Sibling symmetry** — same-level elements use the same spacing tier
3. **Container padding** — parent padding ≥ one tier above child gap (per Container Padding Minimums table)
4. **Touch targets** — mobile interactive elements meet minimums (per Touch Targets section)
5. **Desktop vs mobile scale** — desktop-scale spacing has responsive mobile override (per Desktop vs Mobile Spacing Scale table)
6. **Margin direction** — single direction within a parent (per Margin Direction Consistency rules)

---

## Phase 3: Component-by-Component Audit

Read EACH component file listed below. For each, verify ALL of the following:

1. **Light mode** styling matches design-system.md
2. **Dark mode** styling matches design-system.md
3. **Contrast / visibility** — per Section 17.7 rules
4. **Spacing / padding / margin** — per Section 17.6 rules
5. **Mobile** layout — responsive classes or `useIsDesktop` gating
6. **DS token** usage where applicable (or documented raw pattern per Section 6)
7. **Typography** — follows Section 2 Typography tokens
8. **Borders** — follow Tactile Rule (Section 2) where applicable (interactive elements use `border-2`)

### Component Groups to Audit

**Sheets** (highest priority — user-facing settings):
- `plan/sheets/BaseSheet.tsx`
- `plan/sheets/DestinationSheet.tsx`
- `plan/sheets/OriginSheet.tsx`
- `plan/sheets/TravelersSheet.tsx`
- `plan/sheets/BudgetSheet.tsx`
- `plan/sheets/FlightsSheet.tsx`
- `plan/sheets/StaysSheet.tsx`
- `plan/sheets/ActivitiesSheet.tsx`
- `plan/sheets/TripSettingsSheet.tsx`
- `plan/sheets/DatesSheet.tsx`

**Plan views** (core rendering):
- `plan/StrategyStageRenderer.tsx`
- `plan/stages/StrategyHero.tsx`
- `plan/stages/S2StrategyView.tsx`
- `plan/stages/S3ItineraryView.tsx`
- `plan/NextStepBar.tsx`
- `plan/PlanHeader.tsx`
- `plan/TimelineThread.tsx`
- `plan/TripHealthBar.tsx`
- `plan/BookingSection.tsx`

**Tiles and cards**:
- `tiles/TileCard.tsx`
- `tiles/MiniCard.tsx`
- `tiles/TileDetailsModal.tsx`
- `tiles/TileFilterBar.tsx`
- `plan/tiles/BookableCard.tsx`
- `plan/tiles/SuggestionCard.tsx`

**Timeline blocks**:
- `plan/timeline/blocks/ActivityMiniCard.tsx`
- `plan/timeline/blocks/LogisticsBlock.tsx`
- `plan/timeline/blocks/SafetyBlock.tsx`
- `plan/timeline/blocks/FreeDayCard.tsx`
- `plan/timeline/blocks/GhostSlot.tsx`
- `plan/timeline/blocks/PreferenceAttributionBadge.tsx`
- `plan/timeline/InlineDatePrompt.tsx`
- `plan/timeline/TimelineSkeleton.tsx`

**Chat**:
- `chat/ChatPanel.tsx`
- `chat/SystemAckLine.tsx`
- `chat/SystemReceipt.tsx`
- `chat/SmartLoader.tsx`
- `chat/ChatSkeleton.tsx`
- `chat/MobileChatInput.tsx`
- `chat/MobileSetupCollapsedHeader.tsx`
- `chat/CollapsedSetupSummary.tsx`
- `chat/TripStatusBar.tsx`
- `chat/HoldToDeleteButton.tsx`

**Chips and pills**:
- `plan/CoreChip.tsx`
- `plan/UnifiedChipRow.tsx`
- `plan/TripSummaryPills.tsx`
- `pill/ExpandablePill.tsx`

**Layout**:
- `layout/SplitLayoutView.tsx`
- `layout/FloatingBuildButton.tsx`
- `layout/TripDetailsForm.tsx`
- `layout/MobileModeHeader.tsx`
- `layout/MobileSwipeLayout.tsx`
- `layout/NomadicLanding.tsx`

**Map**:
- `map/InteractiveMap.tsx`
- `map/MapLayerFilter.tsx`
- `map/MapErrorBoundary.tsx`

**Booking**:
- `plan/booking/BookingDrawer.tsx`
- `plan/booking/CategorySection.tsx`
- `plan/booking/CheckoutSidebar.tsx`

**Modals**:
- `plan/modals/AlternativesModal.tsx`

**Shared UI**:
- `ui/calendar.tsx`
- `ui/stepper.tsx`
- `ui/toast.tsx`
- `ui/bottom-sheet.tsx`
- `ui/loader.tsx`

---

## Phase 4: Spec Gap Detection

After auditing all components, identify elements that exist in the codebase but have NO corresponding entry in `docs/design-system.md`.

### 4A: Undocumented Patterns

For each component, look for recurring visual patterns not covered by the spec:

- Toast/notification styling
- Loading skeleton colors and animation
- Error state visuals (error text color, error border, error background)
- Empty state visuals (no-content placeholders)
- Badge/tag patterns beyond constraint pills
- Progress indicators (bars, spinners, loaders)
- Dividers/separators
- Scrollbar styling
- Focus ring patterns
- Transition/animation timing not in animation-config.ts
- Bottom sheet handle/drag styling
- Tooltip appearance
- Popover appearance
- Booking-specific elements (price display, booking status badges)
- Map overlay elements (filter chips, attribution, controls)

### 4B: New Components Not in Component Mapping

Check **Section 6 (Component Mapping)** against the actual file list. Any component NOT listed → add it.

---

## Phase 5: Fix Violations & Extend Spec

### 5A: Fix Code Violations

For each violation found in Phases 1-3:

1. **Low contrast text** → Fix per Section 17.7 Failing Pairs table
2. **Missing dark mode** → Add `dark:` counterpart per Section 4 palettes
3. **Wrong color shade** → Replace with spec-correct value
4. **Spacing violation** → Fix per Section 17.6 tier system
5. **Missing mobile variant** → Add responsive class or `useIsDesktop` gate per Section 17.6 Desktop vs Mobile table
6. **Raw Tailwind with DS equivalent** → Replace with `DS.*` token ONLY if the component already imports DS
7. **Restricted color misuse** → Replace per Section 4 Restricted Colors
8. **Tactile Rule violation** → Add `border-2` and hover snap per Section 2 Tactile Rule

**Priority order:** contrast failures > dark mode gaps > wrong colors > spacing violations > mobile gaps > DS token adoption

### 5B: Extend design-system.md

For each undocumented pattern found in Phase 4:

1. Determine the canonical styling from the most polished component instance
2. Add a new subsection or table row to the appropriate section of `docs/design-system.md`
3. Include both light and dark mode values
4. Include mobile variant if different from desktop

New entries go into the most logical existing section:
- New surface/bg pattern → Section 2 (Design Tokens) under Materials
- New button/action pattern → Section 2 under Actions
- New text style → Section 2 under Typography
- New spacing pattern → Section 17.6 (Spacing Standard)
- New interaction pattern → Section 2.5 (Interaction Patterns)
- New component → Section 6 (Component Mapping)
- New color usage → Section 4 (Color Rules)
- New contrast pair → Section 17.7 (Known-Good Pairs tables)

### 5C: Update Component Mapping

Add any missing components to the Section 6 table with their DS token usage.

---

## Phase 6: Report

Output a summary:

```
## Style Enforcement Report

### Violations Fixed
| Category | Count | Files Touched |
|----------|-------|---------------|
| Low contrast text | | |
| Missing dark mode | | |
| Wrong color shade | | |
| Spacing violation | | |
| Missing mobile variant | | |
| DS token adoption | | |
| Restricted color misuse | | |
| Tactile Rule violation | | |

### Spec Gaps Filled
| New Entry | Added To Section | Description |
|-----------|------------------|-------------|
| ... | ... | ... |

### Component Mapping Updates
| Component | Added/Updated | DS Tokens |
|-----------|---------------|-----------|
| ... | ... | ... |

### Unfixable Items (Need Design Decision)
[List any styling choices that are ambiguous and need human input]
```

---

## Rules

- READ `docs/design-system.md` FIRST. Code must match spec. Spec is SSoT.
- **This command stores NO styling specs.** All color, spacing, contrast, and typography rules live in `docs/design-system.md`. This command only describes what to check and how to apply fixes.
- When code and spec conflict, **fix the code** to match the spec.
- When a pattern exists in code but NOT in spec, **extend the spec** (`docs/design-system.md`) with the pattern.
- Do NOT invent new design tokens or colors. Extract from the best existing instance.
- Do NOT refactor component structure. Only modify className strings and style props.
- Do NOT touch component logic, props, state, or event handlers.
- PRESERVE existing formatting and code structure.
- Maximum 15 component files fixed per run. If more need fixing, prioritize: sheets > plan views > tiles > timeline > chat > layout.
- If a component is too complex to audit in one pass, flag it for a follow-up run.
- For every code fix, verify BOTH light and dark mode are correct after the change.
