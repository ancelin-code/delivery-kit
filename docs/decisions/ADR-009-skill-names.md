# ADR-009: Skills are named by their role, under the `delivery` prefix

**Status:** accepted
**Date:** 2026-10-09

## Context

In a harness a skill name is not branding. It is a line in the slash menu and a
phrase in a lane's prompt, read by someone who has not opened the README. A name
has to say what the skill does, and must not collide with a harness built-in or
a developer's own skill.

## Decision

Skills are named by their role, under the prefix `delivery`:

| Skill | Role |
|---|---|
| `delivery-orchestrator` | Where the project stands, the route, the gates, the lane policy. The entry point |
| `delivery-spec` | Requirements, then decisions and contracts |
| `delivery-decompose` | Approved work into validated task files |
| `delivery-implement` | One task into one validated change |
| `delivery-status` | Claims and run state, read from git |

The entry point reads `/delivery-orchestrator what's next`. It is the
orchestrator because that is its job, and the same pattern as its siblings
rather than a bare `delivery` that would read as one of them. `delivery` also
matches the `delivery/` directory the artifacts live in.

## Alternatives considered

- **A bare `delivery` for the entry point.** Rejected: next to `delivery-spec` it
  reads as a sibling, not as the parent that routes them.
- **`ship-*`.** Rejected: shipping is the last step, and `/ship` is a common name
  for a personal skill, which would shadow ours.
- **Bare verbs such as `/spec` or `/status`.** Rejected: Claude Code has its own
  `/status`, and generic verbs collide with built-ins and personal skills.

## Consequences

- `delivery` is a generic prefix, so a personal skill of that name could shadow
  ours. The README's shadowing check names the skills to look for.
