---
name: nomadic-enforce-style
description: Enforce UI styling consistency against `docs/design-system.md` across all frontend components, including DS token compliance, dark mode, spacing, contrast, and responsive behavior. Use when asked to audit and fix UI style drift or extend the style spec for newly introduced patterns.
---

# Nomadic Enforce Style

## Goal

Align component styling with the design-system SSoT and apply code fixes for violations.

## Required Context

Read these files fully before auditing components:

1. `docs/design-system.md`
2. `frontend/lib/design-system.ts`
3. `frontend/tailwind.config.mts`
4. `frontend/lib/specialists.ts`

## Enforcement Workflow

1. Audit all `.tsx` files in `frontend/components/` (full scan, not diff-based).
2. Check DS token compliance and identify raw Tailwind usage where DS tokens exist.
3. Check dark mode pairings for color/background/border classes.
4. Check mobile responsiveness and touch targets.
5. Check restricted color usage (teal banned; amber/orange restricted).
6. Check emerald and zinc shade consistency.
7. Check text/background contrast and correct failing pairs.
8. Check spacing tier compliance, sibling symmetry, container padding hierarchy, and margin-direction consistency.
9. Audit the high-priority component groups from the source command list (sheets, plan views, tiles/cards, timeline blocks, chat, pills/chips, layout, map, booking, modals, shared UI).

## Fixing Rules

- Apply code changes to bring components into spec.
- Skip allowed exceptions explicitly documented in design-system guidance (for example approved raw patterns and allowed `ui/` primitives).
- If code reveals a valid recurring pattern that is not yet documented, extend `docs/design-system.md` accordingly.

## Reporting

Summarize:

- files changed
- major consistency issues fixed
- spec updates made for previously undocumented patterns
