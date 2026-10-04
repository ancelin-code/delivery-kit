# ADR-006: The kit is named Fourmee, and only the brand changes

**Status:** partly superseded by [ADR-010](ADR-010-alula-name.md). The name and
its metaphor were replaced; the identifier scheme and the kept `delivery/`
directory still stand, with `fourmee` read as `alula`.
**Date:** 2026-10-02

## Context

The kit began as `delivery-kit`, a working title that describes the category
and cannot be searched for, claimed or defended. It is going public, so it
needs a name of its own.

## Decision

**The name is Fourmee**, from *fourmi*, French for ant. The spelling is
invented so that English speakers pronounce it right and a search finds this
project and nothing else. The metaphor is the leafcutter colony: cut work into
pieces small enough to carry, send them along parallel trails, coordinate
through marks left in the shared environment instead of through a central
planner, and size the worker to the job. That is what claims in git refs, lanes
and model tiers do.

What changes:

| Before | After |
|---|---|
| `delivery-orchestrator` | `fourmee`, so the entry point reads `/fourmee what's next` |
| `delivery-spec`, `-decompose`, `-implement`, `-status` | `fourmee-spec`, `fourmee-decompose`, `fourmee-implement`, `fourmee-status` |
| `DELIVERY_WORKTREE_ROOT` | `FOURMEE_WORKTREE_ROOT` |
| `<!-- delivery-kit:routing -->` marker | `<!-- fourmee:routing -->` |
| Skill versions, drifted apart | one version for the kit, restarted at `0.1.0`, `product-version: fourmee@v0` |

What does **not** change: the `delivery/` directory a project holds its
requirements, decisions, contracts and task files in. It says what it contains,
and a project's artifacts read better under `delivery/prd.md` than under a
brand name.

Trending words such as *agent* or *orchestrator* stay out of the name. They
date quickly and every project in the space carries one. They belong in the
tagline, the description and the repository topics.

## Consequences

- A project that installed the kit under its old names must reinstall and
  re-run `install-routing.sh`: the routing marker changed. No public
  installation exists yet, so nothing is migrated.
- Earlier decision records keep their reasoning and use the new names.
