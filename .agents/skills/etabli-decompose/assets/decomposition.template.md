# Decomposition: <project name>

**Status:** draft | approved
**Approved by:** <name, date>

## Source

What this was cut from. The next phase starts here, in a fresh session, so a
reader who saw none of the decomposition must be able to follow it back.

- <link to the approved requirements, `delivery/prd.md`>
- <links to the decision records and `delivery/contracts/` files the cut uses>

## Milestones

Optional: delete this section to cut the whole scope at once. Keep it when the
project is delivered in end-to-end slices, with a review after each. List every
milestone in delivery order. Only the current one has epics; a later one names
its exit and targets, and is cut after the review of the one before.

### <milestone-slug>

<Why this slice comes here: the risk it retires, or what it unlocks.>

**Exit:** <the observable outcome that shows the slice works end to end>
**Requirements:** <requirement ids it targets, `(part)` after one it delivers only in part>
**Epics:** <the epics cut for it, comma-separated; empty until it is cut>

## Epics

One section per epic. State what the slice
delivers, not what its tasks do: the tasks are listed under it, and their
detail is in their own files.

### <epic-name>

<What is observably true once this slice lands. One or two sentences. If it
only restates the task titles below, the grouping has no reason to exist and
the tasks belong to another epic.>

- `<epic-name>-001` - <task title>
- `<epic-name>-002` - <task title>

## Parallelism

Where the set serializes, and what forces it. With milestones, this section and
the critical path describe the current milestone's cut. A set that serializes almost
everywhere is a finding: say serially, and mark every task `parallel: false`.

**Run as:** lanes | serially

- <task ids that cannot run together, and the file or contract that forces it>

## Critical path

<The longest chain of dependencies, as task ids. This is the floor on elapsed
time; every other task has slack against it.>
