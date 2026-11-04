# Établi

**Agent Skills for AI-native delivery.** *Établi* is French for *workbench*.

Établi takes a project from an intent to merged pull requests: requirements
and a design spine, decomposition into tasks, parallel implementation lanes,
review. Each phase writes a file the next one reads, and a person approves it
before the route goes on. Git is the only state: no server, no database, no
status file.

!!! note "Status: early"

    The kit is used on real projects, and `v0.1.0` is its first release.
    Conventions may still change between versions. Install a release tag, read
    the [Changelog](changelog.md) before updating, and expect breaking changes
    to be called out there rather than migrated.

## Who it is for

- **Developers** who want an agent to build more than one change at a time,
  without losing track of what was decided and what is in flight.
- **Teams** that share one task set: several people pick tasks from it, and a
  claim made in git says who holds which.
- Anyone on **Claude Code, GitHub Copilot CLI, Codex CLI, OpenCode or Pi**.
  The skills hold no harness-specific tool names, and the lane launcher has an
  adapter for each, plus a custom command for any other.

## What version 0.1.0 does

- Six skills that are one workflow: `etabli-orchestrator` routes every request,
  `etabli-spec` writes requirements and contracts, `etabli-decompose` cuts them
  into tasks, `etabli-status` claims tasks, and each lane runs
  `etabli-implement` then `etabli-refine`. See [The Six Skills](concepts/skills.md).
- Up to three **lanes** at once, each in its own git worktree, each ending as a
  draft pull request. See [Lanes](concepts/lanes.md).
- **Tiers** instead of model names: a task says how much capability it needs,
  and your own mapping says which model that means. See
  [Choose Models with Tiers](guides/tiers.md).
- **Milestones** for a project too large to cut at once, and **requirement
  coverage** that says what is left of each requirement.
- One project planned **across several repositories**, each task landing where
  its change belongs. See [Several Repositories](guides/repositories.md).
- A JSON **snapshot** of the project that connectors copy into tools such as
  Jira. See [Plug a Connector](guides/connectors.md).

## Where to start

1. [Install the Kit](start/install.md): add the six skills to a repository and
   make the orchestrator its default assistant.
2. [Drive the Route](start/route.md): ask for what you want built, approve each
   phase, and let the lanes run.
3. [Watch and Resume Lanes](start/lanes.md): see what a lane is doing, stop it,
   or pick it back up by hand.
4. [The Route](concepts/route.md): how the phases, the gates and the files fit
   together.

Établi is open source under the Apache-2.0 licence; its code is on
[GitHub](https://github.com/ancelin-code/etabli). Its sibling,
[Tiroir](https://ancelin-code.github.io/tiroir/), was built with it.
