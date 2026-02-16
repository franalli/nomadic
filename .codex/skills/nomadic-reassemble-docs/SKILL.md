---
name: nomadic-reassemble-docs
description: Perform full SSoT reconciliation by reading live source files and correcting documentation drift across architecture, contracts, design system, UX architecture, and repository structure. Use for periodic deep doc syncs after major changes.
---

# Nomadic Reassemble Docs

## Goal

Run a heavy, full-codebase documentation reconciliation. This is not incremental.

## Required Behavior

- Read actual source files listed in `.claude/commands/reassemble-docs.md`.
- Treat code as source of truth.
- Update docs directly to match live behavior.
- Do not skip required phases.

## Phases

1. Reconcile `docs/repo_structure.md` against filesystem.
2. Reconcile `docs/plan_graph_analysis.md` against planner graph, nodes, routing, specialist registry, itinerary builder, caching, regen strategy, services, and streaming.
3. Reconcile `docs/data-contracts.md` against backend routes, schemas, middleware/security, streaming, frontend store, and API client.
4. Reconcile `docs/design-system.md` against DS tokens and Tailwind config, including component mapping and interaction patterns.
5. Reconcile `docs/ux_unified_architecture.md` against state helpers, backend view-state logic, and renderer architecture.

## Validation Expectations

For each reconciled area, remove stale entries, add missing entries, and correct mismatches in tables, enums, field names, signatures, event types, and behavior descriptions.

## Rules

- This command is full-reconciliation and intentionally expensive.
- Read the listed files directly before making doc edits.
- Preserve document structure and clarity while correcting drift.
