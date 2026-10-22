---
name: delivery-status
author: Ancelin Serre
description: >-
  Part of Delivery Kit, used by delivery-orchestrator and by developers directly.
  Claim a delivery task and read run state directly from git, with no shared status file
  and no model reasoning. Use when a developer picks up a task from a decomposed epic, when
  a launcher needs to know whether a task is free before starting a lane, or when asked who
  holds a task. Scripts only: it does not implement tasks or open pull requests.
license: Apache-2.0
repository: https://github.com/ancelin-code/delivery-kit.git
product-version: delivery-kit@v0
version: "0.1.0"
keywords:
  - claim-task
  - delivery-status
  - task-lock
  - parallel-lanes
  - who-holds
spec-version: "1.0"
compatibility:
  - git@>=2.30
  - gh@>=2.0
metadata:
  category: development
  owner: ancelin-code
---

# Delivery Status

Coordination for parallel delivery lanes. Every answer comes from git refs, so
this skill runs deterministically and costs no model tokens.

Task state is **derived, never stored**. There is no status file to update, fall
out of date, or conflict on.

## When to use

- a developer or a lane launcher is about to start work on a task
- something needs to know whether a task is already taken, and by whom

The task file schema, branch naming and tiers are defined by the delivery
conventions, `<delivery-orchestrator>/references/conventions.md`. This skill does not require
them: it reads the task id it is given, the task files in `delivery/tasks/`, and
the git refs around it.

## Claiming a task

Claiming and starting work are the same act: the claim creates the task's remote
branch. Git applies ref creation atomically, so the first push wins.

```sh
sh <skill-root>/scripts/claim.sh ingestion-003
```

Run it from a clone of the repository the task lands in: the one its `repo`
field names, else this one. Status reads every repository of the task set
itself.

Read the exit code, not the output text:

| Exit | Meaning | What to do |
|---|---|---|
| 0 | The claim was won | Start the lane on `task/<id>` |
| 2 | Another developer holds the task | Pick another ready task; do not retry |
| 1 | Usage or environment error | Fix the reported cause |

On exit 2 the script prints the holder and how long ago they claimed it, so a
developer can ask rather than duplicate the work.

Run the claim from the lane's worktree, on the branch `task/<id>`. On success
the local branch is advanced to the claim commit so the lane builds on top of
it. A worktree with uncommitted changes is never reset; the script reports that
it left the branch alone.

Pass `--remote <name>` when the shared remote is not `origin`, and
`--no-advance` to leave the local branch untouched.

## Reading state

```sh
sh <skill-root>/scripts/status.sh
```

One `TASK` row per task with its id, state, holder and title, then a summary
line. Nothing is stored: two people running it at the same moment get the same
answer, because the answer lives in the refs.

| State | How it is derived |
|---|---|
| In progress | the remote branch `task/<id>` exists |
| In review | the task's pull request is open and no longer a draft |
| Done | the task's pull request is merged |
| Ready | every `depends_on` entry is done and no branch exists yet |
| Blocked | some `depends_on` entry is not done |

Narrow the output with `--ready`, `--blocked`, `--in-progress` or `--in-review`.
Use `--ready` to answer "what can I pick up", which is the question that precedes
a claim, and `--in-review` for what is waiting on a person rather than on a lane.

A lane opens its pull request as a draft and leaves it drafted while it works,
so in review is reached by marking it ready for review. Nothing a lane does on
its own moves a task out of in progress.

When `delivery/decomposition.md` plans milestones, the output also carries one
`MILESTONE` row per milestone, in plan order: its slug, its state (`closed`,
`undecomposed`, `active`, `merged`, `reviewing` or `planned`, as the
conventions define them), its epics and the requirement ids it targets. A
filter leaves them out.

Only **merged** work unblocks a dependent. A dependency that is claimed and
under way still leaves its dependents blocked, because nothing has landed yet.

Reading pull request state needs `gh`, authenticated against the repository's
forge. Branches are deleted on merge, so a merged pull request is the only
record that a task is done. Without `gh`, or when it cannot list pull requests,
the script exits 1 rather than report merged work as ready.

For a stand-up, the same data grouped for reading aloud:

```sh
sh <skill-root>/scripts/standup.sh
```

Run both from the repository root. Options common to both: `--tasks-dir <dir>`
when task files are not in `delivery/tasks`,
`--remote <name>` when the shared remote is not `origin`, and `--no-fetch` to
read cached refs instead of refreshing from the remote.

For how much of each requirement merged work covers, from the tasks' `## Covers`
sections and the requirement ids in `delivery/prd.md`:

```sh
sh <skill-root>/scripts/coverage.sh [--milestone <slug>]
```

One `REQ` row per requirement: its id, its state (`covered`, `partly`,
`planned` or `not-started`), the milestones that target it, the merged tasks
and the open ones. A `PART` row follows for each partial cover of a
requirement not yet covered, with the task's note on what it does of it. With
`--milestone`, only the requirements that milestone targets. It takes the same
options as `status.sh` and fails the same way.

For a tool outside git, such as a Jira or Confluence connector, the same state
as one JSON document, with each task's epic, repository, dependencies and pull
request, what each epic delivers, the milestones and the coverage of each
requirement when the project has them, and the project's documents:

```sh
sh <skill-root>/scripts/snapshot.sh
```

It takes the same options and fails the same way, printing nothing, so a
connector never acts on a guessed state. The document carries a `schema`
number; a consumer should refuse one it does not know.

The holder and claim time also come from the claim commit directly:

```sh
git log -1 --format='%an %ar' task/ingestion-003
```

## Boundaries

A claim is a coordination signal, not a permission gate. It records that a task
is taken; it does not protect a branch or enforce review. Branch protection and
pull request review belong to the forge.

Never delete or force-update another developer's task branch to take a task
over. Releasing a task is a human decision: the holder deletes the remote
branch, which makes the task claimable again.

## Acceptance Criteria

- a claimed task has exactly one holder, identifiable from git alone
- a second claim on a held task fails with exit 2 rather than appearing to succeed
- reported state matches the refs at the moment of the call
- no command in this skill writes a status file or requires a model call
