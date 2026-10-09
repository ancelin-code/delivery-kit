# Delivery conventions

The shared contract for Delivery Kit. Task files, branches, claims, tiers
and pull requests follow these rules. Skills reference this file rather
than restating it.

## Placeholders

`<skill-root>` names the root of whichever skill the instruction using it
belongs to, never another one: the same token means a different directory in
each skill's own files. A command spanning two skills names the other one as
`<its-name>` instead, for example `<delivery-status>`, resolved to that
skill's own installed directory the same way `<skill-root>` is. Neither is a
path assumed relative to the skill doing the naming; the kit does not require
one skill to sit at a fixed offset from another.

## Use cases, epics and tasks

Three nested units. Every artifact the kit produces belongs to one of them.

| Unit | What it is | Where it is written |
|---|---|---|
| Use case | The project: one team, one set of requirements, in one repository or [several](#several-repositories) | `delivery/prd.md`, with its decision records and contracts |
| Epic | A coherent slice of the use case, small enough for one person to hold in their head | a section of `delivery/decomposition.md` |
| Task | One unit of work: one branch, one lane, one pull request | `delivery/tasks/<id>.md` |

A use case has exactly one requirements document. New work on the same use case
revises that document and becomes new epics; it does not start a second one.

An epic has no task count: it is as large as one person can hold in their head,
and `delivery-decompose` cuts a bigger group into several.

## Where artifacts live

Every path the kit writes or reads is relative to the root of the repository
holding the plan, under a single `delivery/` directory. Nothing needs searching
for: when a file is not at its path below, it does not exist yet.

| Artifact | Path | Written by |
|---|---|---|
| Requirements | `delivery/prd.md` | `delivery-spec`, stage A |
| Decision records | the repository's existing decision record directory, else `delivery/decisions/ADR-<nnn>-<slug>.md` | `delivery-spec`, stage B |
| Contracts | `delivery/contracts/<interface>.md` | `delivery-spec`, stage B |
| Decomposition summary | `delivery/decomposition.md` | `delivery-decompose` |
| Task files | `delivery/tasks/<id>.md` | `delivery-decompose`, or the orchestrator on the direct path |
| Review lenses | `delivery/review-lenses.conf` | `install-routing.sh` seeds it; the project's maintainers edit it |

An existing decision record directory is one already holding ADR files, such as
`docs/adr/` or `docs/decisions/`. Check those two before creating
`delivery/decisions/`; extending the repository's own record beats starting a
parallel one.

The kit's scripts default to `delivery/tasks` and run from the repository root,
so none of them needs a path argument.

Files shipped with a skill are named from that skill's root, for example
`<delivery-orchestrator>/references/conventions.md` for this file, as
[placeholders](#placeholders) defines.

## Task identity

A task id is an epic-scoped lowercase slug: `<epic>-<nnn>`, for example
`ingestion-003`. Ids are unique within the use case, across all its
repositories.

Task files in git are the source of truth. No issue tracker is in the loop
during a run, so an id never embeds a tracker key.

The id is used verbatim in three places, so it must stay a valid slug
(`^[a-z0-9]([a-z0-9-]*[a-z0-9])?$`):

| Place | Form |
|---|---|
| Task file | `delivery/tasks/<id>.md` |
| Branch | `task/<id>` |
| Worktree | one per task, outside the repository working tree |

## Task file

Frontmatter, then a body an unfamiliar developer could execute without
guessing.

```yaml
---
id: ingestion-003
title: Parse conref references in the DITA loader
type: feat
epic: ingestion
depends_on: [ingestion-001]
parallel: true
conflicts_with: [ingestion-004]
tier: build
review: [security]
---
```

| Field | Meaning |
|---|---|
| `type` | Conventional Commits type of the change, `feat` when absent. Prefixes the commit and pull request title. |
| `depends_on` | Task ids that must be merged first. Empty list means ready at the start. |
| `parallel` | `false` makes the task run alone: it starts only when nothing else of the set is in flight, and nothing starts while it runs. For shared ground too wide for `conflicts_with`, such as a lockfile, a migration or a repository-wide rename. A set that serializes marks every task `false`. |
| `conflicts_with` | Tasks touching the same files. Never run these concurrently, even when both are ready. |
| `tier` | How much capability the work needs: `plan`, `build` or `chore`. Required. See [tiers](#tiers). |
| `review` | Review lenses the pull request needs beyond the general review, see [review lenses](#review-lenses). Optional. |
| `repo` | The repository the change lands in, as the directory name of its clone, when it is not the one holding the plan. See [several repositories](#several-repositories). Optional. |

The body states acceptance criteria as observable outcomes, the files in scope,
and what is explicitly out of scope.

`conflicts_with` is derived when the epic is decomposed, not discovered at run
time.

Nothing here is capped by size: not the requirements, an epic, nor a task. Each
is as long as its reader needs and no longer, which means cutting repetition and
never content.

## Several repositories

A use case often spans repositories: infrastructure, a service, a data pipeline,
a demo app. It still has one plan, held in one of them, the **planning
repository**. Copying planning files into the others would leave several
sources to keep in sync by hand, so nothing is copied.

- **Layout.** Every repository of the use case is cloned side by side in one
  directory, `<use-case>/<repo>`, with the directory named after the repository.
  The kit finds a repository by that name, beside the planning one.
- **Planning repository.** The repository that holds `delivery/`: the one whose
  lifecycle is the use case's. Usually the main code repository; a dedicated
  `<use-case>-hub` repository when three or more share the work evenly.
- **Tasks.** A task names where its change lands with `repo:`. Its claim, branch,
  worktree and pull request are all in that repository; its task file stays in
  the planning one. Dependencies cross repositories freely.
- **Decisions.** A decision about the use case goes in the planning
  repository's record. A decision confined to one repository's internals goes in
  that repository's own record, written by the task that makes it.
- **Contracts.** `delivery/contracts/` holds the agreed interface while it is
  being built. Once built, the repository that produces it owns the as-built
  form (an OpenAPI document, a schema, a published package), and consumers pin
  a version of it. The contract file then points there instead of restating it.

## Claiming a task

A task is claimed by creating the remote branch `task/<id>`. Git applies ref
creation atomically, so the first push wins and there is no shared mutable
status file.

`task/` is a namespace owned by the claim protocol, not a Conventional Branch
type. Change type is carried by Conventional Commits and the pull request title.

```sh
sh <delivery-status>/scripts/claim.sh ingestion-003
```

Run it from a clone of the repository the task lands in.

The claim pushes a commit that is unique to the claiming developer. A plain
push of the current commit is **not** a claim: when the branch already points at
that commit, git resolves the push as a no-op and exits 0, and the second
developer reads success on a task somebody else holds.

Exit codes: `0` claim won, `2` already held, `1` usage or environment error.

## Derived status

Status is never stored. It is read from git:

| State | Rule |
|---|---|
| In progress | `task/<id>` exists on the remote |
| In review | the task's pull request is open and out of draft |
| Done | the task's pull request is merged |
| Ready | every id in `depends_on` is done, and no branch exists yet |
| Blocked | some id in `depends_on` is not done |

The holder and claim time come from `git log -1 task/<id>`.

## Tiers

A task's `tier` says how much capability its work needs. It is a hint, not a
model name: Delivery Kit cannot know which models an account may use, so unless a
tier is mapped (below) the harness picks its own default.

| Tier | For | Typically |
|---|---|---|
| `plan` | Work where a wrong call costs the most: design decisions, contracts, a task with interacting constraints | The most capable model |
| `build` | Execution against explicit acceptance criteria. The default | A balanced model |
| `chore` | Mechanical changes with no judgement in them | The fastest, cheapest model |

Route by what the work needs, not by preference. Putting every task on `plan`
is how a budget disappears.

### Mapping a tier to a model

Which model a tier means depends on the licenses a developer holds, so the
mapping is the developer's. `tiers.conf` names it in git's own config format,
one section per tier, read with `git config`:

```ini
# Which model each tier means, for my licenses.
[plan]
    harness = claude
    model = opus

[build]
    harness = claude
    model = sonnet
    advisor = opus

[chore]
    harness = copilot
    model = gpt-6-luna
```

`harness`, `model` and `advisor` are all optional: a missing `harness` means
any, and a missing `model` means the harness's own default. `advisor` names a
stronger model the lane may consult at its own decision points; only Claude
Code has one, and it must be at least as capable as `model`. Without it, a
lane gets whatever advisor the developer's harness settings name. A mapping
applies only to the harness it names, so a model id never reaches a harness
that would refuse it. A tier that no file names passes no model flag at all.
Comments, quoting and syntax errors are git's.

Two files are read, and the first to name a tier decides all of it:

1. The developer's own: `$DELIVERY_TIERS`, else
   `$XDG_CONFIG_HOME/delivery-kit/tiers.conf` (`~/.config/delivery-kit/tiers.conf`).
   It lives outside every repository, so it is never committed by accident.
2. The project's: `delivery/tiers.conf`, committed when a team agrees on one.

A lane runs on the first of: `--harness`, the harness its tier maps to,
`$DELIVERY_HARNESS`, then the first harness found installed.

## Review lenses

A lens is a concern that deserves its own review pass, such as security or
data. The project names its lenses in `delivery/review-lenses.conf`, one per
line: the lens, the review skill that covers it (`-` for none), and optionally
the path patterns that bring it in.

```text
# lens     skill             paths that bring the lens in
general    code-review
security   security-review   */auth/* *.tf
data       databricks-dbsql  *.sql */pipelines/*
```

A pattern matches the whole path of a file the pull request changes, and `*`
crosses directories. `general` applies to every pull request. The skill names
are the project's choice: the kit ships no reviewer.

A pull request needs a lens when any of these holds:

- its task lists the lens in `review`, set at decomposition
- a person labelled the pull request `review:<lens>`
- it changes a file matching one of the lens's patterns

The orchestrator's `where.sh` resolves these for every task in review. Without
the file, only the general review is suggested, and it is the harness's own.

## Commits and pull requests

A lane does not commit. When its session exits cleanly,
`<delivery-orchestrator>/scripts/publish-lane.sh` commits the worktree as
`<type>(<epic>): <title>`, pushes it, and opens the draft pull request. The body
is the lane's handoff report, written in the repository's pull request template
when there is one, else the task's acceptance criteria followed by the report.
The lane worktree holds nothing but the task's work, so it stages all of it.

Anywhere else, the harness already knows git. These are the conventions it
cannot infer:

- Conventional Commits for every commit, including the claim commit
- one pull request per task, opened as a **draft**
- label `ai-assisted`
- honor the repository pull request template when one exists
- stage named paths, never a blanket `git add -A`
- the pull request links its task file and repeats its acceptance criteria

Write the pull request body as the **final state** of the change: what it does
and how to verify it. Reviewers do not need the session history, the approaches
abandoned along the way, or a narrative of how the agent arrived at the result.

## Definition of done

A task is done when its acceptance criteria hold, the validation proportional to
the change has been run and reported, and the documentation pages affected by
the change have been updated in the same pull request. Plans live in
`delivery/`; as-built truth lives in the regular documentation pages.
