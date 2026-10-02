# ADR-007: Tasks name a capability tier, and the developer maps it to a model

**Status:** accepted
**Date:** 2026-10-02

## Context

A task carried a `model` label, one of `opus`, `sonnet`, `terra`, `luna` and
`haiku`. The label chose the harness and the model, and so which of two
separate allowances paid for the lane. The launcher held a table from each
label to a model id per harness, and fell back to the other harness when a
label's default had no binary installed.

That was built for one setup: two licenses, from two vendors, that do not pool.
Everywhere else it is wrong in three ways:

- it names vendors' products, so a task file is out of date when a model is
  renamed, and unusable for a developer with other models
- the kit cannot know which ids an account may use. Copilot CLI refused ids the
  kit had shipped (`harness-validation.md`, test 7), after the claim and the
  worktree already existed
- it fixes the harness list at two, with the budget logic woven through the
  launcher

## Decision

**A task names a tier, a hint about how much capability its work needs, and the
developer decides what that means.**

- The task field `model` becomes `tier`, one of `plan`, `build` or `chore`. It
  stays required: the cost choice should be a conscious one, and a task that
  omits it is read as `build` only by the launcher, never by the validator.
- A tier is not a model name. With nothing mapped, the launcher passes no model
  flag and the harness applies its own default.
- A `tiers.conf` maps a tier to a harness and a model, either optional. Two
  files are read and the first to name a tier wins: the developer's own, outside
  every repository, then `delivery/tiers.conf` for a team that agrees on one.
- A mapping applies only to the harness it names. A model id means nothing to
  another harness, and passing it through would end the session at startup.
- A lane runs on the first of `--harness`, the harness its tier maps to,
  `FOURMEE_HARNESS`, then the first harness installed.
- The launcher holds no model ids, and no longer falls back between harnesses
  for a label. A harness somebody chose is never swapped for another.
- A malformed mapping stops the launch and names its file and line. A typo must
  not quietly fall back to the harness default.

**Reasoning effort is removed**, the task field and the `--effort` flag both,
which supersedes [ADR-002](ADR-002-reasoning-effort.md). That decision treated
effort as an axis independent of the tier, and it is, but a level means
something only for a particular model: the levels one harness accepts another
refuses, and what `high` costs depends on the model behind it. Fourmee no longer
chooses the model, so it cannot choose a level that fits it, and only the
developer knows which model runs the lane. Effort belongs to the harness's own
settings, where it is set once for the model in use. The validator rejects a
leftover `effort` field and says so, so a stale value is never taken for one
that is applied.

## Alternatives considered

- **Keep the vendor labels and add more** - Rejected. Every new model or harness
  becomes an edit to the kit, in the validator, the launcher and the conventions
  table, and a task file would outlive the model it names.
- **Capability names in the task, model ids in the task file too** - Rejected.
  The ids depend on each developer's licenses, so a committed id fails for
  whoever lacks it.
- **Environment variables per tier** - Rejected. They cannot carry a harness
  beside a model, and several tiers would need several variables. A file reads
  better and can be shared as a project default.
- **An effort column in `tiers.conf`** - Rejected. It would work, since a
  mapping already names a harness and a model, but it makes the kit own a flag
  per harness and keep the accepted levels current as they change. The harness
  already has a setting for it, which is the better home.
- **No required field, with `build` everywhere** - Rejected. Routing everything
  to one tier is how a budget disappears, and a required field is the one prompt
  that makes the decomposition say which tasks are worth more.

## Consequences

- Nothing is lost by default: with no `tiers.conf` a lane runs on the installed
  harness's own default model, which is what most developers want.
- Reproducibility moves to the developer. Two people can run the same task on
  different models. That was already true of the harness defaults the kit
  relied on, and a team that wants one answer commits `delivery/tiers.conf`.
- The two-allowance routing is still possible, as a mapping that sends `chore`
  to one harness and `build` to another. It is a use of the mapping, not part of
  the kit.
- The `model` field is rejected with a message that names the tiers, and the
  `effort` field with one that says it was removed, so a task set written before
  this change fails at validation, not at launch.
- A lane's reasoning effort is whatever the harness is configured to use. Two
  lanes on the same tier can think for different lengths of time if their
  developers configured different defaults. That is the cost of not owning the
  setting, and it follows from not owning the model.
- The `LAUNCHED` and `WOULD-LAUNCH` rows lose their effort column, so the
  worktree and repository fields move up by one.
- Adding a harness is now one entry in the launcher's list, plus how to start
  it, not a row in a routing table.
