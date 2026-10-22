# ADR-011: A lane refines its change in a second session, one tier up

**Status:** accepted
**Date:** 2026-10-22

## Context

A lane went straight from `delivery-implement` to a draft pull request. The
only quality pass was the human review at the merge gate, which the kit itself
names as its bottleneck: three lanes at most, because one person has to review
what they produce. Nothing reviewed a change before that person did, and
nothing simplified it.

The maintainer's own practice, outside the kit, is: implement in one agent
session; then review, fix the findings and simplify in another session, on a
stronger model (Haiku reviewed by Sonnet, Sonnet by Opus); then commit and push
a draft.

Two findings from published work shaped the design:

- A second review is worth what the reviewer can do. In a controlled study of
  150 planted errors over 900 review sessions, a fresh-context review by the
  same model scored about the same as self-review (28.6 against 27.1 F1, not
  significant). A top-tier reviewer of another family scored best (32.3), and a
  lightweight one was no better than self-review (24.0). Tests and other
  executable checks remain the main oracle.
  ([arXiv 2610.01471](https://arxiv.org/html/2610.01471v1))
- Simplification tools converge on running after the code works, scoped to what
  changed, preserving behaviour exactly, and refusing line count as a measure.
  Examples are Anthropic's `code-simplifier` agent, Claude Code's `/simplify`,
  EveryInc's `ce-simplify-code` and the `code-simplification` skill in
  `addyosmani/agent-skills`.

## Decision

A sixth skill, `delivery-refine`, is the second session of every lane. The
launcher starts it in the lane's worktree after `delivery-implement` exits
cleanly and left a change, and before `publish-lane.sh` commits and pushes.

- **One pass, in order:** review the change against the task's acceptance
  criteria, fix the findings that name a concrete failure, simplify only the
  lines the change added or modified, re-run validation, and add a Refinement
  section to the report. Fixing comes before simplifying, so no effort goes into
  polishing code about to change, and the fixes get tidied too.
- **One tier up:** the session runs as the tier above the task's would, on its
  harness and model: `chore` as `build`, `build` as `plan`, `plan` as `plan`. A
  tier can name its own `reviewer` in `tiers.conf` instead, a model for the
  tier's own harness. When the tier above maps to another harness, the review
  also gets a second model family.
- **Never lose the implementation:** a refinement that fails is logged as
  `REFINE-FAILED`, noted in the report, and the change is published as
  `delivery-implement` left it. A refinement that finds the task wrong reports
  it as open on the draft pull request; it does not revert.
- **On by default,** `--no-refine` to skip. The cost is a session per lane, in
  tokens, not in a person's time.

The session is started by the launcher, not by a harness's own subagent
mechanism. Subagents differ between harnesses; a second session through
`harness.sh` works on every adapter, `custom` included.

## Alternatives considered

- **A second step inside `delivery-implement`.** That is one session, so no
  fresh context and no stronger model. It would also give a skill evaluated on
  implementing a second job, and the two could not be measured apart.
- **Simplify while implementing, by instruction only.** `delivery-implement`
  already asks for the smallest edit and for reuse. While writing, a session
  optimises for the criteria it is meeting and cannot see the finished diff,
  where duplication across files and abstractions that turned out unneeded
  show. The instruction stays; it does not replace the pass.
- **Review on the same model.** The study above found no reliable gain from
  same-model fresh-context review over self-review, so a second session on the
  same model would cost a session for little.
- **Loop until the review is clean.** The kit's review budget is one pass for a
  reason: later passes find less than they cost.
- **Leave it to the merge gate.** That gate stays, unchanged. Refinement takes
  work off it; it does not replace it.

## Consequences

Every lane costs a second session, on a more expensive model. Whether it pays
is the kit's own rule to prove: the phase 6 evaluation compares lanes with and
without refinement, on human review findings per pull request, diff size,
validation and cost. Until then, `--no-refine` is one flag away.

The launcher's `LAUNCHED` and `WOULD-LAUNCH` lines gain two columns, the review
harness and model, after the lane's model; the worktree and repository stay
last.

The human reviewer reads a Refinement section in each pull request body, which
says what the review fixed, what it deferred, and what it simplified.
