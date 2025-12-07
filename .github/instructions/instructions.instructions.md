## applyTo: "\*\*"

# Engineering Rules

- Prefer simple, minimal solutions; avoid abstractions unless they clearly reduce complexity.
- Eliminate dead code, duplicated logic; reuse or consolidate existing code.
- Correct over-engineered or redundant patterns when encountered.
- Assess system-wide impact before modifying existing code.
- Clearly comment every non-trivial function, class, and module.

# Frontend (React + Tailwind)

- Use functional React + hooks; keep components small and logic DRY.
- Use Tailwind utilities directly unless a shared abstraction reduces repetition.
- Maintain consistent styling and theming across components to enforce branding.

# Backend (Python + Docker)

- Always use the `.venv` environment for Python execution.
- Keep modules small and cohesive; avoid unnecessary layers.
- Ensure code runs cleanly in Docker; avoid reliance on local state.
