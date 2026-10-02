# ADR-001: Claim branches live in a `task/` namespace, outside the Conventional Branch vocabulary

**Status:** accepted
**Date:** 2026-09-22

## Context

The kit claims a task by creating the remote branch `task/<id>`, and derives
status by asking whether that ref exists. Conventional Branch would name the
same branch by change type, `feat/<description>` or `fix/<description>`, which
is the convention the rest of the repository follows for commits.

Two properties of the claim protocol constrain the name. `claim.sh` and
`status.sh` must both compute the ref from the task id and nothing else, with no
file read and no lookup, or the lock stops being a pure function of the id. And
the ref has to be somewhere a human branch cannot collide with it, because a
collision reads as a task already claimed.

## Decision

Claim branches are `task/<id>`, where `<id>` is the task id verbatim. The
`task/` prefix is a namespace owned by the claim protocol, not a change type.
`refs/heads/task/*` holds claims and nothing else.

Change type is carried by Conventional Commits on every commit, including the
claim commit, and by the pull request title. Nothing that consumes change type -
release notes, versioning, review routing - reads branch names.

## Alternatives considered

- **`feat/<id>`, `fix/<id>` and the rest of the Conventional Branch vocabulary** -
  the type is a property of the change, so it would have to become a task
  frontmatter field, and every status read would then have to parse task files
  to learn which ref to look for, or glob `refs/heads/*/<id>` and match by
  suffix. Both weaken a lock whose value is that it is derivable and atomic.
- **Two refs per task: `task/<id>` as a lock that is never merged, plus
  `feat/<id>-<slug>` for the work and the pull request** - conceptually the
  cleanest, since one ref stops serving as lock, workspace and deliverable at
  once. Rejected for cost, not for correctness: two refs to create and clean up,
  status has to correlate them, and "done" gains a layer of indirection between
  the claim and the merged pull request. Reconsider if claims ever need to
  outlive their branches.
- **Encoding the type in the task id** - ids are epic-scoped and used verbatim
  as filenames, branch names and worktree names. Overloading them with a second
  taxonomy makes every one of those harder to read.

## Consequences

A claim is one atomic ref creation whose name follows from the task id, so any
tool can compute it and no tool needs shared state. Claims are trivially
listable and deletable as a group, and a developer's own branches cannot be
mistaken for one.

The cost is a real and visible deviation from Conventional Branch. A reviewer
scanning branch names cannot tell a feature from a fix without opening the task
file or the pull request, and any tooling that keys off branch-name conventions
will not recognise these branches. Both are accepted because the audience for a
claim ref is the claim protocol, not a human browsing the branch list.
