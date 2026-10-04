# ADR-009: Harnesses are adapters in one file, with a custom command as the way out

**Status:** accepted
**Date:** 2026-10-04

## Context

The worktrees, claims and draft pull requests were already harness-neutral. Only
the line that starts a session knew `claude` and `copilot`, written as two
branches inside the launcher. Adding a harness meant editing the launcher, and
nobody can test every harness: a paid license is needed for most.

## Decision

`delivery-orchestrator/scripts/harness.sh` holds everything the launcher knows about a
harness, and is sourced by it. For each one it answers: the binary, how a prompt
is given without a terminal, the flag that picks a model, the flag that grants
access to the planning checkout, how an unattended session is allowed to act,
and what `--no-web` turns off. The launcher resolves *which* harness runs a
lane, and the adapter decides *what* the command line is.

Five adapters ship: `claude`, `copilot`, `codex`, `opencode` and `pi`. `auto`
tries them in that order. A sixth name, `custom`, runs `ALULA_LANE_CMD`, a
shell command line with `{prompt}`, `{model}`, `{worktree}` and `{plan_dir}` in
it, so a harness nobody has written an adapter for works on the first day.
Placeholders become references to environment variables and never pasted text,
so a prompt or path holding quotes or `$(...)` stays a value.

A lane is told to start by reading the skill file, except on Claude Code, and on
Copilot CLI inside the repository that holds the skills, which resolve
`/<skill>`. That form needs no skill discovery from the harness, which differs
between them: OpenCode did not list the kit's symlinked skills in a trial.

**Support has two levels, and the docs say which is which.** *Validated* means
a real lane ran on the real CLI and the result is in
[harness-validation.md](../harness-validation.md). *Adapter only* means the
command line follows the harness's documentation and a stand-in binary proves
the launcher passes it, but nobody has run it for real. Claude Code and Copilot
CLI are validated; the others are adapter only until someone with the license
runs the checks and records them.

Cursor CLI is not an adapter. Its headless mode exists, but its documentation
says nothing on whether it reads `AGENTS.md` or Agent Skills, and Pi was chosen
for the fifth place instead.

## Alternatives considered

- **One adapter file per harness.** Rejected for five short branches: a reader
  compares them side by side more often than they open one alone.
- **Adapters as data (a table of flags).** Rejected: the harnesses differ in
  structure (a subcommand, an environment variable, a repeated flag), so a table
  grows a mini-language. Plain `set --` lines are the shortest honest form.
- **Refuse harnesses that cannot enforce `--no-web`.** Not needed: Codex and Pi
  have no web tool in the way they are run, and OpenCode takes the permission as
  inline config.

## Consequences

- Adding a harness is one branch in `harness_run`, one tested command line, and
  one column in the validation matrix.
- Safety is not equal across harnesses. Claude Code and Copilot deny
  `terraform apply` and `destroy`; OpenCode denies them through its config;
  Codex relies on its sandbox; Pi has no permission system and should run in a
  container. The README says so.
