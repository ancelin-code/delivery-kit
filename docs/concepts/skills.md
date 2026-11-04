# The Six Skills

| Skill | Owns | Produces | Runs as |
|---|---|---|---|
| `etabli-orchestrator` | Where the project stands, the route, the gates, the lane policy | decisions about what happens next | a human's session |
| `etabli-spec` | Requirements (stage A), then decisions and contracts (stage B) | `delivery/prd.md`, decision records, `delivery/contracts/` | a human's session |
| `etabli-decompose` | Splitting approved work into epics and independent tasks | `delivery/decomposition.md` and `delivery/tasks/<id>.md`, validated | a human's session |
| `etabli-status` | Claims and run state, read from git | exit codes and tab-separated rows | `sh`, no model |
| `etabli-implement` | One task into one validated change | a working tree and a handoff report | an unattended lane |
| `etabli-refine` | Reviewing that change, fixing what the review finds, and simplifying it | the same working tree, and a Refinement section in the report | the same lane, a second session on a stronger model |

Only `etabli-orchestrator` is invoked by a human directly. The rest are reached
through it, or through `launch-lanes.sh`.

## Refinement, the second session

`etabli-refine` is the second session of every lane. It did not write the
change, it runs on the [tier](../guides/tiers.md) above the task's, and it
works in one pass: review the change against the task's acceptance criteria,
fix what that finds, then simplify the lines the change added without altering
their behaviour, and re-run validation.

Simplifying last means the fixes get tidied too, and no effort goes into
polishing code about to change. A failed refinement never loses the
implementation: the change is published as it was, and the report says so.
`--no-refine` on the launcher skips it.

## Why the spec is one skill

`etabli-spec` covers two stages rather than shipping as two skills: they are
written in one sitting from the same source material, and the design spine is
worthless without approved requirements to hang it on.

## Review is not shipped

Review is deliberately **not** part of the kit: use the harness's own review
capability, or install a review skill alongside the kit and compare it against
the unassisted harness before adopting it.

To have the orchestrator suggest which review skill a pull request needs, map
concerns such as security or data to installed skills in
`delivery/review-lenses.conf`; see
[Choose review skills](../start/install.md#choose-review-skills).

## The rule behind every skill

A skill must beat what the harness does unassisted on its task, or be free. A
rule stays in the kit only if removing it measurably degrades results. The kit
exists because an earlier skill lost to an unassisted harness by adding
ceremony the model did not need.
