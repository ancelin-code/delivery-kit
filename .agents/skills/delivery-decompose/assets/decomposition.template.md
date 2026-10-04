# Decomposition: <use case name>

**Status:** draft | approved
**Approved by:** <name, date>

## Source

What this was cut from. The next phase starts here, in a fresh session, so a
reader who saw none of the decomposition must be able to follow it back.

- <link to the approved requirements, `delivery/prd.md`>
- <links to the decision records and `delivery/contracts/` files the cut uses>

## Epics

One section per epic, within the task cap the skill sets. State what the slice
delivers, not what its tasks do: the tasks are listed under it, and their
detail is in their own files.

### <epic-name>

<What is observably true once this slice lands. One or two sentences. If it
only restates the task titles below, the grouping has no reason to exist and
the tasks belong to another epic.>

- `<epic-name>-001` - <task title>
- `<epic-name>-002` - <task title>

## Parallelism

Where the set serializes, and what forces it. A set that serializes almost
everywhere is a finding: say serially, and mark every task `parallel: false`.

**Run as:** lanes | serially

- <task ids that cannot run together, and the file or contract that forces it>

## Critical path

<The longest chain of dependencies, as task ids. This is the floor on elapsed
time; every other task has slack against it.>
