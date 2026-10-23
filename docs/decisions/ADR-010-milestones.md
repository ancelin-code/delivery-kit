# ADR-010: Milestones cut and run a project slice by slice, with a review between

**Status:** accepted
**Date:** 2026-10-22

## Context

A pilot project, a self-hosted memory server, has about eighty approved
requirements in one `delivery/prd.md`. The document is deliberately complete,
so lanes can build without asking questions. The team still wants to deliver
in milestones: first a walking skeleton that runs the riskiest parts (remote
connector, sign-in, deployment) end to end, then full retrieval, then team
features, then the rest. After each, they want to stop and look at what was
learned. That might lead them to revise the requirements or a decision record,
or to cut the next slice.

The kit had nothing between project and epic. `delivery-decompose` cut the
whole approved scope at once, so lessons from the first slice could not shape
the second. `where.sh` and `follow.sh` saw one flat task set, which reads as
complete once everything is merged. A task could not say that it delivers only
part of a requirement, such as sign-in without revocation, so nobody could tell
what was left of each requirement.

## Decision

A **milestone** is an optional, ordered group of epics with an observable exit
criterion. Requirements and the design spine stay project-wide and are written
in full up front; only decomposition and execution are incremental.

- **The plan** is a Milestones section of `delivery/decomposition.md`. Each
  milestone has an `**Exit:**` line, a `**Requirements:**` line with the
  requirement ids it targets, and an `**Epics:**` line that stays empty until
  the milestone is cut.
- **The current milestone** is the first whose review note is not approved.
  Only that milestone, and the closed ones before it, have task files. The
  validator rejects a task of a later milestone, and it rejects a cut that
  leaves one of the current milestone's targets uncovered.
- **The gate** is an artifact, `delivery/milestones/<slug>.md`. It records
  whether the exit criterion held, the coverage, what was learned, and whether
  to continue or revise. Approving it closes the milestone. Cutting the next
  milestone puts the summary back to draft, and the existing decomposition gate
  covers the new cut.
- **Requirement ids** take the form `- **<id>.**` in the requirements. A task
  lists the ids it covers under `## Covers`, with `(part): <note>` after one it
  delivers only in part.
- **Coverage is derived**, like task state, by
  `delivery-status/scripts/coverage.sh`. It reports each requirement as covered,
  partly covered, planned or not started, and names the tasks behind it.
- **State is derived** by `status.sh`, which prints a `MILESTONE` row per
  milestone, so `where.sh`, `follow.sh` and `coverage.sh` share one reading of
  the plan. `where.sh` names the review, its approval or the next cut. At the
  boundary, `follow.sh` stops with `MILESTONE` instead of `COMPLETE`.

A plan without a Milestones section, and tasks without `## Covers`, take
exactly the code paths they took before.

## Alternatives considered

- **A gate on a step, with no artifact.** Cutting the next milestone would mean
  "continue". This is lighter, but it was rejected for two reasons. What the
  review learned would die with its session, although the next decomposition
  starts in a fresh one and needs it. And `where.sh` could not tell a reviewed
  milestone from one nobody looked at.
- **The review as a section of `decomposition.md`.** This would avoid a new
  file. It was rejected because it merges two gates, a look back at a finished
  slice and approval of the next cut, and reopens an approved summary just to
  record a retrospective.
- **A separate plan file, `delivery/milestones.md`.** The grouping of epics
  already lives in the summary, and ADR-003 rejected per-group files for the
  drift they invite. A milestone is one more level of the same grouping.
- **A `milestone:` field on every task.** This would be a third copy of a
  membership already held by the task's epic and the milestone's `**Epics:**`
  line.
- **One requirements document or decomposition per milestone.** This breaks one
  requirements document per project, and the requirements of later milestones
  are exactly what lanes of earlier ones must not contradict.
- **Coverage declared in the requirements.** This would reopen an approved
  stage-A document on every cut, the reason ADR-003 kept the feature index out
  of it.
- **Coverage in frontmatter, as `covers` and `partly` lists.** Frontmatter is
  one key per line with inline lists, so it has no room for the note that says
  what a partial cover leaves.
- **Decomposing ahead, with later tasks held back by a new task state.** This
  would let the next cut overlap the current milestone. It was rejected because
  it costs a state in `status.sh` and filtering in every consumer, and it
  defeats the point of learning before cutting. Forbidding such tasks is
  cheaper than scheduling around them.

## Consequences

A large project gets a stop after each slice, recorded where the next phase
reads it, and an answer to "what is left of each requirement" that needs no
reading of code.

The parser of the Milestones section exists twice: once in `status.sh` and once
in `validate-tasks.sh`. The validator runs offline and without `gh`, and a
skill cannot reach into a sibling's files. The tests drive both against the
same plan shape.

The exit criterion is not machine-checked. Only a person running the slice can
say it works end to end, and the review note records the evidence they saw.

`snapshot.sh` carries both, as `milestones` and `requirements` lists beside
the epics and tasks, so a connector can show a slice's progress and what is
left of each requirement. They are added fields, so the schema number stays 1,
as ADR-005 allows.
