# ADR-003: Decomposition writes a summary artifact, not only task files

**Status:** accepted
**Date:** 2026-09-22

## Context

The kit's phases communicate through files: each one ends by writing an
artifact, and the next starts from it in a fresh session, so no long-lived
session has to carry state. Decomposition was the exception. It wrote
`tasks/<id>.md` and then *reported* the epics, what could run in parallel and
the critical path into the session that produced them.

That made the epic a concept with no artifact anywhere in the kit. It survived
only as an id prefix (`<epic>-<nnn>`), a frontmatter field, and a cap of ten
tasks. The grouping itself - which tasks form a slice, and what that slice is
responsible for delivering - existed in one session's reasoning and was gone
when the session ended.

Two consequences followed. The human standing at the decomposition approval
gate was handed a directory of loose task files and a verbal summary that no
later phase could read, which is the hardest form in which to judge whether a
cut is sane. And while "is this epic finished" is derivable from git, "does
this epic deliver what it was grouped to deliver" had nowhere to be written,
even though integration is exactly where parallel lanes fail.

## Decision

`fourmee-decompose` writes `decomposition.md` beside the task directory, from
a template that ships with the skill. It records the source artifacts the cut
was made from, one section per epic naming what that slice delivers and which
tasks belong to it, where the set serializes and what forces it, and the
critical path.

`validate-tasks.sh` requires the file and cross-checks it against the task
files in both directions: a declared task must have a file carrying the same
epic, and every task file must appear in the summary.

The epic stays a grouping rather than becoming an artifact of its own. Nothing
in the kit gains an `epics/` directory.

## Alternatives considered

- **One file per epic, `epics/<name>.md`** - the shape most task runners use.
  Rejected because the drift surface scales with the number of epics while the
  membership it would restate already lives in task frontmatter. The reasoning
  worth keeping is about the cut as a whole - what serializes against what -
  and that has no natural home in a per-epic file.
- **A feature index inside the requirements document** - no new artifact, and
  it is how many product specs carry the same information. Rejected because it
  puts a decomposition concern into a stage-A document a human already
  approved, so every re-cut reopens an approved artifact and blurs which gate
  covers what.
- **Leaving it as a session report** - what the kit did. Rejected because
  decomposition was the only phase not writing its output, and what it reported
  is precisely what the approval gate needs to read.
- **Deriving the summary from the task files at read time** - attractive,
  since the ids, epics and dependency graph are all in frontmatter. Rejected
  because the parts worth writing down are the ones that are not derivable:
  why these tasks are one slice, and what the slice owes. A generated file
  would restate what the reader could already compute and omit the judgement.

## Consequences

Every phase now ends by writing a file, so the rule the kit states about itself
is true without exception. The approval gate has one reviewable artifact
instead of a directory listing, and a fresh session in any later phase can
recover why the work was cut the way it was.

The cost is deliberate duplication. The epic names and task ids appear both in
frontmatter and in the summary, because a reviewer needs the set in one place.
That duplication is why the validator checks it in both directions, and the
check is what keeps it honest.

The prose parts - what a slice delivers, the serialization points, the critical
path - are not machine-checkable and can still go stale if a task set is re-cut
carelessly. The validator catches a changed *set*, not changed *reasoning* about
an unchanged set. That residue is accepted; the alternative is a summary
restricted to what a script can verify, which would exclude everything the
artifact exists to carry.

Requiring the file makes it non-optional in practice: a task set without one
fails validation, so no lane starts from a cut nobody wrote down.
