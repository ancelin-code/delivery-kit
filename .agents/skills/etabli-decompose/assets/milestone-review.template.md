# Milestone review: <milestone-slug>

**Status:** draft | approved
**Approved by:** <name, date>

## Exit criterion

<The exit line from `delivery/decomposition.md`, then whether it held and the
evidence: what was run, against which deployment, and what was observed. A
criterion nobody exercised did not hold.>

## Coverage

<The output of `coverage.sh --milestone <milestone-slug>`, and for each
requirement it reports as partly covered or not started: why, and where the
rest goes.>

## What we learned

<What building this slice taught that the requirements, the decision records
or the plan did not know: a wrong assumption, a cost, a risk retired or found.
Only what changes something later; leave out what went to plan.>

## Decision

**Decision:** continue | revise

<Continue: the next milestone is cut as planned, and anything below adjusts
it. Revise: name each artifact to change (`delivery/prd.md`, a decision
record, the milestone plan) and what changes. Each is revised and approved
through its own gate before the next milestone is cut.>

## Carried over

<What the next cut must take into account: requirements left in part, work
deferred from this milestone, follow-ups found in review. Empty when nothing
is.>
