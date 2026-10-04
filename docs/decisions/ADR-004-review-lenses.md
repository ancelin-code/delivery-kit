# ADR-004: The orchestrator names a review skill per lens, from a project map

**Status:** accepted
**Date:** 2026-09-23

## Context

Review is the final gate, and the kit deliberately ships no reviewer. But in
practice that left the user with no guidance at review time. `where.sh`
reported a task as in review, and nothing said which review to run on it, even
when the project had installed specialised review skills for security or data
work.

Pull request labels were considered as the selection signal and rejected as
the primary one. By the time a label exists, the only party that could have set
it unprompted is the lane that wrote the change, which would be grading its own
work, or a person doing it by hand on every pull request.

## Decision

A lens is a concern worth its own review pass. The consuming project maps each
lens to a review skill, and optionally to path patterns, in
`delivery/review-lenses.conf`. A pull request needs a lens when:

- its task file lists it in the optional `review` field, set at decomposition,
  when the task's files and contracts are known and a human approves the cut
- a person labels the pull request `review:<lens>`, which is the override
- the diff touches a path matching one of the lens's patterns, which catches
  what decomposition missed

`where.sh` resolves this in sh for every task in review and prints one
`REVIEW` row per lens, so "what's next" and "what's the status" name the skill
to run. `general` applies to every pull request.

The review still runs where it did before: in a fresh session a human starts,
not inside `delivery-implement`. The lane does not add labels itself, because
`gh pr create --label` fails when the label does not exist in the repository.

## Consequences

- The kit still ships no reviewer and names no harness tool: skill names live
  in the consuming repository's file.
- Each pull request in review costs one extra `gh pr view` call in `where.sh`.
- Whether a lens beats the general review it sits beside is not established by
  this change. Map a lens only to a skill that carries knowledge the general
  review lacks, and drop it when it does not measurably find more.
