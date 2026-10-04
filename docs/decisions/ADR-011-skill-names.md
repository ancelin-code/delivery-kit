# ADR-011: Skills are named by what they do, and Alula names the project

**Status:** accepted
**Date:** 2026-10-04
**Supersedes:** the skill names in [ADR-010](ADR-010-alula-name.md)

## Context

[ADR-010](ADR-010-alula-name.md) named the project Alula and, with it, the
skills: `alula`, `alula-spec` and so on. In a harness a skill name is not
branding. It is a line in the slash menu and a phrase in a lane's prompt, read
by someone who has not opened the README. `/alula-implement` tells that reader
nothing, where `/delivery-implement` says what it does.

## Decision

**Alula is the name of the project. The skills are named by their role, under
the prefix `delivery`:**

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

What keeps the brand: the repository, the documentation, the decision records,
the `ALULA_*` variables, the `alula:routing` marker, `~/.config/alula/`, the
`product-version: alula@v0` field, and the "part of Alula" in each skill's
description, so a reader can find where a skill comes from.

## Alternatives considered

- **Keep `alula-*`.** Rejected: the brand in every command costs the reader
  meaning, and the entry point was the worst case.
- **`ship-*`.** Rejected: shipping is the last step, and `/ship` is a common name
  for a personal skill, which would shadow ours.
- **A bare `delivery` for the entry point.** Rejected: next to `delivery-spec` it
  reads as a sibling, not as the parent that routes them.
- **Bare verbs such as `/spec` or `/status`.** Rejected: Claude Code has its own
  `/status`, and generic verbs collide with built-ins and personal skills.

## Consequences

- `delivery` is a generic prefix, so a personal skill of that name could shadow
  ours. The README's shadowing check names the skills to look for.
- Names a reader sees and names the project is known by now differ on purpose.
- Nothing is public, so no migration is carried.
