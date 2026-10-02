# ADR-002: Reasoning effort is a task field with a batch override

**Status:** accepted
**Date:** 2026-09-22

## Context

Every lane runs at a pinned reasoning effort, because an unset effort lets each
harness apply its own default and two lanes on the same tier then think for
different lengths of time, for no stated reason.

The value has to come from somewhere. The task file already carries a `model`
label that routes the lane, so the question is whether effort belongs beside it
or belongs to the launch.

The case for the launch is that effort looks like a restatement of the tier:
work needing more thought needs a more capable model. The case against is
concrete and decides it. Designing a frontend and planning a change both want
`opus`, and they do not want the same amount of deliberation. Implementing a
feature wants `sonnet` at medium. Tier and effort are independent axes: the tier
is the class of judgement the work needs, the effort is how much deliberation
this particular task needs within it.

## Decision

`effort` is an optional task frontmatter field, validated against the levels
both harnesses accept: `low`, `medium`, `high`, `xhigh`, `max`. A task that
omits it runs at medium.

The launcher's `--effort` overrides every task in the batch, the same way
`--harness` overrides the harness implied by the model label. The task states
what its work needs; the operator overrides when the run, not the task, is what
changed.

Copilot CLI also accepts `none` and `minimal`, which Claude Code rejects. Both
the validator and the launcher accept only the intersection, so a task set
cannot validate and then fail at launch on one side only.

## Alternatives considered

- **A batch flag only, with no task field** - Rejected. It forces one effort on
  every lane in a launch, and the designed path pipes every ready task into one
  launch. Raising the effort of a single task would mean launching it on its
  own, which breaks that composition. The result is that nobody changes the
  effort, or they edit the script, which then applies to every later run.
- **Leaving effort unset and taking each harness default** - Rejected. This is
  what the kit did while the conventions claimed execution ran at medium. The
  claim was false and nothing surfaced it.
- **Deriving effort from the model label** - Rejected. It is the assumption the
  frontend example breaks: the same tier legitimately wants different amounts of
  thinking on different tasks.

## Consequences

`fourmee-decompose` now sets a second cost knob, and the failure mode is
one-directional: marking every task `high` looks like diligence and spends real
budget, while being less visible than raising the tier. The conventions carry a
level-by-level table and the instruction to leave it absent unless the task is
genuinely harder than the others. Nothing enforces that, and a run whose tasks
are uniformly above medium is worth questioning at the decomposition gate.

A task repeatedly needing high effort is still evidence about the
decomposition. The field does not remove that signal, but it does make it
easier to absorb rather than act on.
