# Changelog

All notable changes to Alula are recorded here. The kit is installed whole,
so one version covers every skill. Set the date on a release's heading when
tagging it.

## [Unreleased]

## [0.1.0] - Unreleased

First public release.

- Five skills that take a use case from requirements to draft pull requests:
  `delivery-orchestrator`, `delivery-spec`, `delivery-decompose`, `delivery-implement` and
  `delivery-status`.
- Parallel implementation lanes with claims made by create-only git pushes, so
  git is the only state.
- Tasks name a capability `tier` (`plan`, `build` or `chore`) instead of a
  vendor's model. A `tiers.conf` maps a tier to a harness and a model; with
  none, the harness picks its own default. Reasoning effort is left to the
  harness's own settings.
- The helpers are POSIX `sh`: no bash is required, and they run on dash, macOS's
  own `sh` and BusyBox ([ADR-008](docs/decisions/ADR-008-posix-sh-helpers.md)).
- Harness adapters for Claude Code, Copilot CLI, Codex, OpenCode and Pi, and a
  `ALULA_LANE_CMD` template for any other
  ([ADR-009](docs/decisions/ADR-009-harness-adapters.md)).
- Multi-repository use cases planned once and landed where each change belongs.
- A status snapshot that external tools can project into their own views.
- Licensed under Apache-2.0.
