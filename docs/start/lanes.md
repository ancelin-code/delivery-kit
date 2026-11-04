# Watch and Resume Lanes

## Watch a running lane

Lanes run detached, one process per task, with no terminal attached. Each
writes everything it does to `.lanes/logs/<task-id>.log` under the main
checkout (`--log-dir` moves it).

A lane's log prints `REFINE` when its second session starts, `PUBLISHED` with
the pull request URL when it ends well, and `REFINE-FAILED` if the review
session failed and the change was published as the first session left it.

```sh
tail -f .lanes/logs/a-001.log          # follow one lane
tail -n 40 .lanes/logs/*.log           # where each lane got to
pgrep -af 'claude -p|copilot -p'       # which lanes are still alive
```

The worktree is the other live view. The commands below name it once, from
the planning repository, wherever the launcher put it:

```sh
home=$PWD
lane=${DELIVERY_WORKTREE_ROOT:-../lanes/$(basename "$home")}/a-001
git -C "$lane" status                  # what the lane has changed
git -C "$lane" log --oneline           # what it has committed
```

That is usually a faster answer than reading its log.

## Stop a lane

To stop a lane, kill its process, then remove the worktree and the claim:

```sh
pkill -f 'tasks/a-001\.md'          # a lane is known by its task file
git worktree remove --force "$lane"
git push origin --delete task/a-001
```

Deleting the remote branch is what releases the claim. Skip it and the task
stays held by you and nobody else can pick it up.

A lane whose task names a `repo` belongs to that clone, not to the planning
repository: its worktree is registered there, and its claim is on that
repository's origin. Run the last two commands against the clone, for
`repo: shop-iac`:

```sh
git -C ../shop-iac worktree remove --force "$lane"
git -C ../shop-iac push origin --delete task/a-001
```

## Pick a lane back up by hand

You cannot type into a running lane: `-p` sessions have no input attached.
What you can do is resume the conversation once it has finished or stopped, in
the same worktree, with its context intact.

Copilot lanes print the command to do it as their last line, so it is already
in the log:

```sh
grep -h 'copilot --resume' .lanes/logs/a-001.log
cd "$lane" && copilot --resume=<session-id>
```

Claude lanes do not print a session id in text mode, so there is nothing in
the log to resume from. Use `claude --continue` from inside the lane worktree,
which picks up the most recent session for that directory:

```sh
cd "$lane" && claude --continue
```

That is reliable only while the lane is the last session started in that
worktree. When it is not, start a fresh session there and point it at the task
file and the branch:

```sh
cd "$lane" && claude "/etabli-implement $home/delivery/tasks/a-001.md"
```

To redo only the review of a change the first session already left in the
worktree, run `/etabli-refine` on the same task file and `--report
.lane-report.md` instead.

Claude Code can also run lanes as attachable background sessions
(`claude --bg`, then `claude attach <id>`), which would remove this asymmetry
on the Claude side. The launcher does not use it: Copilot CLI has no
equivalent, the logs come back as raw terminal output, and a background
session waits for input instead of exiting, so a stuck lane would hold its
claim indefinitely.
