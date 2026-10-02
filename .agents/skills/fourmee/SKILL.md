---
name: fourmee
author: Ancelin Serre
description: >-
  The project's delivery assistant and the entry point of Fourmee. Answers where
  the project stands, what to do next, and who is working on what, from delivery/ and git;
  and routes any request to build or change the project through requirements, design,
  decomposition, lanes and review, holding the approval gates and the lane policy. Use for
  "what's next", "what's the status", progress, blockers, or any new work on a project
  that has a delivery/ directory or asks to start one. Delegates the work itself to the
  other Fourmee skills; it does not write requirements, code, or pull requests.
license: Apache-2.0
repository: https://github.com/ancelin-code/fourmee.git
product-version: fourmee@v0
version: "0.1.0"
keywords:
  - delivery-workflow
  - orchestrator
  - parallel-lanes
  - decomposition
  - approval-gates
spec-version: "1.0"
compatibility:
  - git@>=2.30
  - bash@>=4.4
  - gh@>=2.0
metadata:
  category: development
  owner: ancelin-code
---

# Delivery Orchestrator

The entry point to Fourmee: it routes a use case from intent to merged
work, deciding **what happens next** and **where a human must approve**. It does
not do the work itself.

The kit is the family of skills named `fourmee` and `fourmee-*`. They are one workflow, not a menu:
each phase consumes the file the previous one wrote, so a phase cannot start
before the phase ahead of it has written its artifact. Reach the other skills
through this one.

## Where the project stands

For "what's next", "what's the status", "who is on what", and before starting
any phase, run this from the repository root and answer from its output:

```sh
bash <skill-root>/scripts/where.sh
```

It prints each phase's artifact and whether it is approved, the task rows and
their derived state, and one or more `NEXT` lines stating what to do now. Do not
re-derive any of it by reading files or git: the script applies the rules below.
Exit 1 means state could not be read, usually `gh`; report the error, do not
guess.

For every task in review it also prints `REVIEW` rows, one per lens: the task,
its pull request, the lens, the review skill mapped to it, and why the lens
applies (`default`, `task`, `label`, or `path:<file>`). List each task in review
with its pull request and the skills to run on it. A skill of `-` means no skill
is mapped: suggest the harness's own review through that lens, and mention that
a skill can be mapped in `delivery/review-lenses.conf`. When a named skill is not
installed, say so by name rather than substituting another. The file's format
is in the [review lenses](references/conventions.md#review-lenses) convention.

A `NEXT install-routing` line means this project's `AGENTS.md` does not yet send
requests here. Run the command it names once, and mention it in the answer.

## Conventions

Read [delivery conventions](references/conventions.md) once per run. It defines
what a use case, an epic and a task each are, plus the task schema, branch
names, claims, model labels and pull request rules, and the other skills rely on
it rather than repeating those rules. It also fixes where every artifact below
lives: all paths here are relative to the repository root, under `delivery/`.

## The route

Each phase ends by writing a file. The next phase starts from that file in a
fresh context, so a long session never has to stay alive to carry state.

| Phase | Produces | Delegate to | Gate |
|---|---|---|---|
| Requirements | `delivery/prd.md` | `fourmee-spec` (stage A) | **Human approves** |
| Design spine | decision records in `docs/adr/`, `docs/decisions/` or `delivery/decisions/`, and `delivery/contracts/<interface>.md` | `fourmee-spec` (stage B) | **Human approves** |
| Decomposition | `delivery/decomposition.md`, plus `delivery/tasks/<id>.md` per task | `fourmee-decompose` | **Human approves** |
| Lanes | a draft pull request per task | `fourmee-status`, then `fourmee-implement` | none, runs unattended |
| Review | findings on the pull request | the review skill each `REVIEW` row names, else the harness review | **Human approves the merge** |

Approval gates sit on **artifacts**, not on steps. Once decomposition is
approved, lanes run unattended up to a draft pull request. Pull request review is
the final gate.

## Choosing the ceremony

Investigate before choosing depth. Read the request and the code, then pick:

- **Direct implement** for a single well-understood change with obvious
  acceptance criteria, belonging to no epic.
- **Full route** when the work spans several tasks, needs contracts so that
  parallel work stays consistent, or touches a decision worth recording.

Choosing the full route for a one-task change wastes a day of ceremony.
Choosing direct implement for genuinely parallel work produces conflicting code.

Whether a full-route set runs in parallel is decomposition's finding, not a
choice made here: tasks marked `parallel: false` run alone, and a set that
serializes marks them all. The phases and gates are the same either way. When
one person holds a serial set, skip the launcher and invoke `fourmee-implement`
per task in dependency order; the claim only earns its keep when several people
pick from the same tasks.

### Direct implement

Write one task file, `delivery/tasks/<id>.md`, from
`<fourmee-decompose>/assets/task.template.md`, then invoke `fourmee-implement`
on it in the ordinary checkout. Nothing else in this skill applies.

Skip the claim, the worktree, the launcher, `fourmee-status` and all three
approval gates. Those coordinate concurrent lanes and guard artifacts this path
does not produce. Do not create an epic, and do not run
`<fourmee-decompose>/scripts/validate-tasks.sh`: it enforces the full schema
and will reject a task trimmed for this path.

Keep the task file. `fourmee-implement` halts without explicit acceptance
criteria, and the file is what the diff is checked back against and what the
pull request points at. Only `id` and `title` carry meaning here: the dependency
and conflict fields order lanes, and `model` routes a launcher that never runs.

Commit and open the pull request as usual afterwards. Review is unchanged.

## Starting a phase

1. Check that the delegate skill is installed. If it is not, stop and name the
   skill the user needs to install. Do not improvise its job.
2. Confirm from `where.sh` that the previous phase's artifact exists and was
   approved. An unapproved artifact is the signal to stop and ask, not to
   proceed.
3. Load only that phase's inputs. Phases communicate through files.

## Lane policy

- one task, one branch, one worktree, one pull request
- claim before starting, by invoking the `fourmee-status` skill. A task reported
  as held is taken: choose another rather than retrying
- at most three lanes at once, regardless of how many tasks are ready
- never start two tasks that list each other in `conflicts_with`, even when both
  are ready
- a task marked `parallel: false` runs alone: nothing else of the set in flight
  while it does
- a lane that reveals its task is wrong **stops**. Save the attempt, revert, and
  raise it. Do not widen scope to make a bad task work

Start lanes with the launcher, which claims, creates the worktree, starts the
session and publishes its result as a draft pull request, and refuses a task
whose claim it loses:

```sh
bash <skill-root>/scripts/launch-lanes.sh --dry-run <task-id>...
```

Once the first lanes are launched, keep the set moving with the follow loop
instead of polling `where.sh`:

```sh
bash <skill-root>/scripts/follow.sh -- <the launcher options you used>
```

It launches each task as the merges it depends on land, within the same limits,
and prints one line per event: `PUBLISHED`, `MERGED`, `LAUNCHED`, `LANE-FAILED`,
and `COMPLETE` or `STUCK` when it exits. Run it in the background where the
harness reports a background command's output as it arrives, and tell the user
about the lines that need them: a pull request to review, a failed lane, a stuck
set. Merging stays with the user; the loop never merges.

The full lifecycle, the limits and what to do when a lane does not finish are in
[lanes](references/lanes.md). The review budget and the two lenses worth running
are in [review](references/review.md).

## Stopping rules

Stop and hand back to a human when any of these holds:

- an artifact needed by the next phase is missing or unapproved
- a required delegate skill is not installed
- two repair attempts on the same failure have not fixed it
- implementation shows the requirements are wrong

Re-review only when review found a high-severity issue, or three medium findings
plus at least two low ones. Otherwise one review pass is the budget.

## Boundaries

The harness owns permission modes, plan mode, worktree isolation and model
selection. This skill does not re-implement them, and does not wrap git or pull
request commands the harness already performs well.

## Supporting Files

- [Position](scripts/where.sh) - phase states, task states and the next action,
  in one call
- [Routing installer](scripts/install-routing.sh) - adds
  [the routing block](assets/agents-routing.md) to the project's `AGENTS.md`
  and a [starter review lenses file](assets/review-lenses.conf), idempotently
- [Lane launcher](scripts/launch-lanes.sh) - claims a task, creates its worktree,
  and starts an unattended session, capped and conflict-aware
- [Lane publisher](scripts/publish-lane.sh) - commits a finished lane, pushes it,
  and opens its draft pull request; the launcher runs it
- [Follow loop](scripts/follow.sh) - launches tasks as their dependencies
  merge and reports each lane's outcome, until the set is merged or stuck
- [Lane release](scripts/release-lane.sh) - gives the task back when a lane's
  session failed without doing anything; the launcher runs it

## Acceptance Criteria

- every phase transition happened through a file, not a live session
- each of the three artifact gates was approved by a human before the next phase
- no lane ran on a task claimed by somebody else, and no two conflicting tasks ran together
- a missing delegate skill was reported by name instead of being improvised
