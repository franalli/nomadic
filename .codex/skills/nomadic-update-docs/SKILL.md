---
name: nomadic-update-docs
description: Update SSoT documentation incrementally based on git diff (staged and unstaged; fallback to last commit when clean). Use when code changes should be reflected in docs without doing a full repo reconciliation.
---

# Nomadic Update Docs

## Workflow

1. Read git diff (staged + unstaged).
2. If no local changes exist, use the last commit diff.
3. Map changed file paths to target docs using the mapping table in `.claude/commands/update-docs.md`.
4. Update only affected sections in each matched doc.
5. Preserve unchanged sections, formatting, table structures, and ordering.
6. Cap modifications to six docs, prioritized by:
- `docs/plan_graph_analysis.md`
- `docs/data-contracts.md`
- `docs/ux_unified_architecture.md`
- `docs/design-system.md`
- `docs/repo_structure.md`
- agent docs
7. Update `CLAUDE.md` sprint block fields only where allowed:
- update `Active work`
- update `Known broken`
- do not modify `Focus`, `Secondary`, `DO NOT touch`

## Agent-Doc Updates

Update `.claude/agents/*.md` only when invariants or patterns changed (not for normal feature edits), following conditions in `.claude/commands/update-docs.md`.

## Unknowns

If a section should change but source-of-truth is unclear, insert:

```html
<!-- TODO: verify after [description of change] -->
```

Do not guess.

## Rules

- Do not regenerate whole docs.
- Patch only diff-impacted sections.
- Skip doc edits entirely when only tests/comments changed and no contract/behavior shifts occurred.
