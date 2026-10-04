# Lanes

A lane is one task, one branch, one worktree, one session, one pull request.
This file holds the policy the orchestrator applies when starting and ending
them.

## Lifecycle

1. A task becomes **ready**: every dependency merged, no branch yet.
2. A developer or the launcher **claims** it, which creates `task/<id>` on the
   remote. The claim is what makes the work exclusive.
3. A **worktree** is created on that branch, outside the main working tree:
   `../lanes/<repository>/<id>` from the repository root by default, where
   `<repository>` is the directory name of the checkout the launcher ran from,
   or `<dir>/<id>` when `FOURMEE_WORKTREE_ROOT=<dir>` is set in the
   environment or `--worktree-root <dir>` is given.
4. A **session** runs in that worktree, unattended, to a validated working tree.
5. When the session exits cleanly, the launcher runs
   `sh <skill-root>/scripts/publish-lane.sh`, which commits the change, pushes
   it, and opens a **draft pull request** whose body is the lane's handoff
   report, in the repository's pull request template when it has one. A session
   that left no change publishes nothing.
6. After the pull request merges, the worktree is removed.

A task with a `repo` field runs the whole lifecycle in that repository's clone,
beside this one: claim, branch, worktree and pull request. The session is given
read access to this repository for the task file, contracts and decisions.

Steps 1 and 2 are separate on purpose. Readiness is a property of the graph;
claiming is a race. A task can be ready for three people and claimed by one.

## Starting lanes

The launcher takes task ids and does the rest. It reads ids from arguments or
from standard input, so it composes with whatever decided they were ready:

```sh
sh <fourmee-status>/scripts/status.sh --ready \
  | awk '$1 == "TASK" { print $2 }' \
  | sh <skill-root>/scripts/launch-lanes.sh
```

Lanes can fetch and search the web unless the launcher is given `--no-web`.
Web content is untrusted input to an unattended session with a shell, so that
choice belongs to whoever launches.

`sh <skill-root>/scripts/follow.sh` then keeps the set moving: it launches each
task once its dependencies merge, skipping any that conflicts with work in
flight, which a single launch cannot see.

Use `--dry-run` first when the task set is unfamiliar. It makes every decision
and prints the outcome without creating a worktree or starting a session.

`<fourmee-status>` and `<skill-root>` are two different skills' roots; see
[placeholders](conventions.md#placeholders).

The launcher claims every task before starting it, using
`<fourmee-status>/scripts/claim.sh`. It finds that copy beside itself, so
`--claim-script <path>` is only needed when a repository has relocated the
scripts. It refuses a task whose claim it loses, removing the worktree it had
created: losing a claim is routine, not an error. A claim that fails for any other reason stops that lane and says
so, rather than being reported as a lost race.

## Limits that are not negotiable

**At most three lanes at once.** The limit is not the machine; it is the human
who has to review the output and integrate it. More lanes produce more work in
flight than anyone can land, and the tokens spent on the surplus are wasted when
those branches go stale.

**A task marked `parallel: false` runs alone.** The launcher starts it only when
nothing else of the set is in flight, on any developer's machine, and starts
nothing while it is. A set that serializes marks every task, so it runs one lane
at a time with no flag to remember.

**Never start two tasks that conflict.** Tasks that touch the same files cannot
be merged independently, however ready both look. The launcher checks
`conflicts_with` in both directions, so a conflict declared on one side only
still holds.

**One task per lane.** A session that implements two tasks produces a diff that
cannot be reviewed against either one's acceptance criteria.

## Tier

The task's `tier` says how much capability the lane needs, and a `tiers.conf`
maps it to a model when the developer has one; otherwise the harness picks its
default, as the [delivery conventions](conventions.md#tiers) define. `--harness`
overrides a whole batch, for example to move a launch to a harness whose
allowance still has room.

## When a lane does not finish

- **The session failed.** An expired login or a model the account cannot use
  ends it at once. When it left no change and no commit past the claim, the
  launcher runs `sh <skill-root>/scripts/release-lane.sh`, which gives the
  task back and removes the worktree; the log ends with `RELEASED`. A failed
  session that left work behind is kept, claim and all, for a human to look at.
- **Stalled on a real blocker.** The session stops and reports. Leave the
  branch, record the blocker against the task, and pick another task.
- **The task turns out to be wrong.** Stop. Do not widen the scope to make it
  work. The task goes back for correction, and the attempt is reported. The
  attempt is reverted, so no pull request opens; the report is in the log.
- **Published, but not by the publisher.** A failed commit hook, push or `gh`
  call leaves the change in the worktree and an `ERROR` line at the end of the
  log. Fix the cause, then re-run the publisher from the worktree:
  `sh <skill-root>/scripts/publish-lane.sh delivery/tasks/<id>.md`.
- **Repeated failure.** After two repair attempts on the same failure, hand it
  to a human. A third automatic attempt rarely differs from the second.

Never delete or force-update another developer's task branch to take work over.
Releasing a task is a human decision: the holder deletes the remote branch,
which makes it claimable again.

## Cleanup

Remove a lane's worktree only after its pull request has merged and nobody needs
the tree:

```sh
git worktree remove ../lanes/<repository>/<id>
```

Session logs are written to `.lanes/logs/<id>.log` under the repository root
the launcher ran from, or under `--log-dir` when given. They are the record of
what an unattended lane actually did, so keep them until the pull request is
reviewed.
