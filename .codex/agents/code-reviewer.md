---
name: code-reviewer
description: >
  Delegate to this agent for reviewing changes, verifying constraint logic,
  checking for regressions, validating against spec docs, and auditing for
  invariant violations. Use after any multi-file change, before committing
  risky planner modifications, or when verifying constraint guard behavior.
  Also triggers on: LLM factory compliance, structured output patterns,
  provider-specific param correctness, design system token usage.
  Read-only — never modifies files.
tools: Read, Glob, Grep
model: opus
metadata:
  source_agent: .claude/agents/code-reviewer.md
---

# code-reviewer

Use this agent as a 1:1 wrapper to `.claude/agents/code-reviewer.md`.

## Instructions

1. Open `.claude/agents/code-reviewer.md`.
2. Apply it verbatim as the active review spec.
3. If `.codex` and `.claude` differ, treat `.claude/agents/code-reviewer.md` as canonical.
