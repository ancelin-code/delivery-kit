# Changelog

All notable changes to Delivery Kit are recorded here. The kit is installed whole,
so one version covers every skill. Set the date on a release's heading when
tagging it.

## [Unreleased]

## [0.1.0] - 2026-10-23

First public release.

- Six skills that take a project from requirements to draft pull requests:
  `delivery-orchestrator`, `delivery-spec`, `delivery-decompose`,
  `delivery-implement`, `delivery-refine` and `delivery-status`.
- Parallel implementation lanes with claims made by create-only git pushes, so
  git is the only state. A lane's branch pushes to itself: a plain `git push`
  from a lane worktree reaches `task/<id>`, never the default branch.
- Every lane is two sessions: `delivery-implement`, then `delivery-refine`, which
  reviews the change on the tier above, fixes what it finds, simplifies it
  without changing its behaviour, re-validates, and adds a Refinement section to
  the pull request body. A tier can name its own `reviewer` in `tiers.conf`;
  `--no-refine` skips the second session
  ([ADR-011](docs/decisions/ADR-011-lane-refinement.md)).
- Tasks name a capability `tier` (`plan`, `build` or `chore`) instead of a
  vendor's model. A `tiers.conf` maps a tier to a harness and a model; with
  none, the harness picks its own default. Reasoning effort is left to the
  harness's own settings.
- Milestones: a large project is cut and run one end-to-end slice at a time,
  with a reviewed note closing each before the next is cut. `where.sh` and
  `follow.sh` stop at each boundary
  ([ADR-010](docs/decisions/ADR-010-milestones.md)).
- Requirement coverage: requirements carry ids, tasks list the ids they cover
  in full or in part, and `coverage.sh` reports what is left of each.
- A status snapshot that external tools can project into their own views,
  including milestones and coverage.
- An install split between `.claude/skills/` and `.agents/skills/`, as
  `npx skills update` can leave, is reported by `where.sh` as
  `NEXT repair-install`, and the lane launcher refuses to start without
  `delivery-implement` or `delivery-refine`. The README explains how to install
  so this cannot happen, and how to repair it.
- The helpers are POSIX `sh`: no bash is required, and they run on dash, macOS's
  own `sh` and BusyBox ([ADR-007](docs/decisions/ADR-007-posix-sh-helpers.md)).
- Harness adapters for Claude Code, Copilot CLI, Codex, OpenCode and Pi, and a
  `DELIVERY_LANE_CMD` template for any other
  ([ADR-008](docs/decisions/ADR-008-harness-adapters.md)).
- Multi-repository projects planned once and landed where each change belongs.
- Licensed under Apache-2.0.
