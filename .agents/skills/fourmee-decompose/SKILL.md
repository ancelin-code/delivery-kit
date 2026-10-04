---
name: fourmee-decompose
author: Ancelin Serre
description: >-
  Part of Fourmee, invoked by fourmee. Break approved requirements
  and their design spine into task files that parallel lanes can execute independently,
  with dependencies, file conflicts and tiers made explicit, then validate the set
  deterministically. Use when work has been approved and needs splitting into tasks, or
  when an existing task set needs checking before lanes start. Does not implement tasks or
  decide requirements.
license: Apache-2.0
repository: https://github.com/ancelin-code/fourmee.git
product-version: fourmee@v0
version: "0.1.0"
keywords:
  - decompose
  - task-breakdown
  - epics
  - dependencies
  - parallel-work
spec-version: "1.0"
compatibility:
metadata:
  category: development
  owner: ancelin-code
---

# Decompose Work

Turns approved intent into task files that several developers can pick up at
once without colliding.

The output is the contract every later step reads: lanes are launched from it,
status is derived from it, and a merge order falls out of it. A weak
decomposition is not discovered until several people are already building.

## When to use

Run this after the requirements and the design decisions are approved. Running
it earlier produces tasks that encode guesses, which then have to be rewritten.

For a single well-understood change, skip decomposition entirely and implement
it directly. Splitting a one-task change into an epic costs more than it saves.

## Workflow

1. **Read the approved artifacts**: `delivery/prd.md`, `delivery/contracts/`,
   and the decision records in `docs/adr/`, `docs/decisions/` or
   `delivery/decisions/`, whichever `fourmee-spec` wrote to. Read enough of
   the codebase too to know what already exists, including the use case's other
   repositories when they are cloned beside this one. Decomposing from the
   requirements alone invents work that is already done.
2. **Group work into epics**, as the delivery conventions,
   `<fourmee>/references/conventions.md`, define them. A group
   past the cap below is two epics, not one large one.
3. **Write one task file per unit of work**, from
   [the template](assets/task.template.md), into `delivery/tasks/<id>.md`.
4. **Derive the dependency edges.** A task depends on another only when it
   genuinely cannot start without the other's merged output. Dependencies
   invented "to be safe" serialize work that could have run in parallel.
5. **Derive the file conflicts.** List the files each task will touch, then
   record `conflicts_with` for any pair whose file sets intersect. Two tasks
   editing the same file are not parallel, however independent they look. Set
   `parallel: false` on a task whose shared ground is too wide to list, such as
   a lockfile, a migration or a repository-wide rename: it then runs alone.
6. **Write the decomposition summary** to `delivery/decomposition.md`, from
   [the template](assets/decomposition.template.md). It states what each epic
   delivers, where the set serializes and why, and the critical path. When it
   serializes almost everywhere, say **Run as:** serially and mark every task
   `parallel: false`; the validator holds the two in step. The task files carry
   the work; this carries the reasoning behind the cut, which no later session
   can recover from them.
7. **Validate the set** before anyone starts:

   ```sh
   sh <skill-root>/scripts/validate-tasks.sh
   ```

   Run it from the repository root; it reads `delivery/tasks/` and
   `delivery/decomposition.md`. Exit 0 accepts the set, 2 reports what to fix,
   1 is a usage error. Fix every reported failure. A set that fails validation
   stalls lanes hours later, when it is expensive to correct. It cross-checks the summary against the task
   files in both directions, so re-cutting tasks without revisiting the summary
   fails here rather than at the approval gate.

## Writing a task

The quality bar: an unfamiliar developer with no context should be able to
execute the task without asking a question. That is also what an agent in a
fresh session needs.

Every task states what must be true when it is done, which files are in scope,
and what is deliberately out of scope. The acceptance criteria are observable
outcomes, each checkable by running something, not restatements of the title.

Caps, because both cost and reviewability depend on them:

- at most 10 tasks per epic
- a task body of at most 30 lines
- no restating the requirements document; link `delivery/prd.md`

Give each task a `tier` from the tiers table in
`<fourmee>/references/conventions.md`. Match it to what the task needs: `plan`
where a wrong call costs the most, `build` for ordinary execution, `chore` for
mechanical work. The tier only says how much capability the work needs, and the
developer's own mapping decides which model that means.

Set `type` to the Conventional Commits type of the change when it is not a
feature: the lane's commit and pull request title are built from it and the
title.

Set `repo` when the use case spans repositories and the task's change lands in
another one than this: the directory name of its clone beside this repository,
as the conventions' section on several repositories describes. One task changes
one repository; a change that needs two is two tasks with a dependency, usually
through a contract.

Set `review` to the lenses the task's change will need beyond the general
review, taken from `delivery/review-lenses.conf` when the project has one: a
task handling credentials needs `security`, one changing a table schema needs
the data lens. Leave it empty when the general review suffices. The file's
path patterns catch what this misses, so name a lens only when the task makes
it evident.

## Boundaries

This skill decides how work is split, not what the work is. When decomposition
reveals that the requirements are wrong or incomplete, stop and say so rather
than inventing scope to fill the gap.

Dependencies and conflicts are derived here, once, from evidence. They are not
rediscovered at run time by the lanes.

## Acceptance Criteria

- every task file validates, and the validator exits 0
- no dependency exists that is not a genuine ordering constraint
- every pair of tasks touching a shared file declares the conflict
- each task states observable acceptance criteria and its files in scope
- `delivery/decomposition.md` exists, names what every epic delivers, and lists the same
  tasks under the same epics as the task files do
