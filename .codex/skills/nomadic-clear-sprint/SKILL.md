---
name: nomadic-clear-sprint
description: Reset the `## 🎯 Current Sprint` section in `CLAUDE.md` to a standard placeholder template while preserving everything else. Use when asked to clear, reset, or reinitialize the sprint block before new work starts.
---

# Nomadic Clear Sprint

## Workflow

1. Open `CLAUDE.md`.
2. Locate the `## 🎯 Current Sprint` heading.
3. Replace only the content from that heading until the next `---` horizontal rule with the template below.
4. Do not modify any other section.
5. Confirm with the exact message: `Sprint cleared. Fill in the placeholders in CLAUDE.md before starting work.`

## Replacement Template

```markdown
## 🎯 Current Sprint (UPDATE EVERY SESSION)

- **Focus:** [describe focus]
- **Secondary:** [secondary priority or "none"]
- **Active work:** [update per session]
- **Known broken:** [update per session]
- **DO NOT touch this sprint:** [frozen files/features]
```

## Hard Rules

- Modify only the sprint section.
- Leave Hard Rules, Governance, Architecture, and all other sections untouched.
