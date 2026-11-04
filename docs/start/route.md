# Drive the Route

## Ask for what you want built

Tell the orchestrator what you want built:

```text
/etabli-orchestrator <what to build>
```

In a repository with no `delivery/prd.md` yet, that starts the requirements.
Once the file exists, the same request revises it, and decomposition turns the
new work into new epics. The repository is the project, so there is never a
second one to start.

Ask it where things stand at any time, in your own words: *"what's next?"*,
*"what's the status?"*, *"who is on what?"*. The answer comes from
`etabli-orchestrator/scripts/where.sh`, which reads `delivery/` and git in one
call and names the next action. For each pull request in review, it also names
the review skills to run on it.

## Approve each phase

Each invocation routes one phase, which ends by writing its artifact under
`delivery/` and stopping. Approve that artifact, then invoke the orchestrator
again for the next phase: it keeps nothing between them and re-reads where you
are from `delivery/`, so no session has to stay alive across a gate.

The phases and their gates are described in [The Route](../concepts/route.md).

## Start the lanes

To start lanes once tasks are approved:

```sh
sh .agents/skills/etabli-status/scripts/status.sh --ready \
  | awk '$1=="TASK"{print $2}' \
  | sh .agents/skills/etabli-orchestrator/scripts/launch-lanes.sh --dry-run
```

Drop `--dry-run` to start real lanes. Each lane ends as a draft pull request:
once its session exits cleanly, `publish-lane.sh` commits the change, pushes
it, and opens the pull request with the lane's handoff report, written in the
repository's pull request template when it has one. A lane that stopped on a
bad task reverts its attempt and publishes nothing. A lane whose session failed
before doing anything, on an expired login for example, gives its claim back
by itself. Tasks marked `parallel: false` are held back until they can run
alone, so re-run the launcher after each merge.

!!! danger "Lanes have web access by default"

    A lane can fetch pages and search the web, which helps it read a library's
    documentation, and it is a prompt-injection path: the lane runs unattended
    with a shell and your git credentials, and a fetched page is text the model
    may act on. Pass `--no-web` to the launcher when lanes should build from
    the repository and its contracts alone, for example on a codebase with
    secrets in reach. It removes the web tools on every harness; the shell can
    still reach the network, so it narrows the path rather than closing it.

## Let the set run itself

The follow loop launches each task as the merges it depends on land, and
prints one line per event, so nobody has to ask what is next or refresh the
forge:

```sh
sh .agents/skills/etabli-orchestrator/scripts/follow.sh -- --no-web
```

Options after `--` go to the launcher. Your part is reviewing and merging the
pull requests it reports; it never merges, and it exits once every task is
merged, or when the remaining tasks can never become ready. With milestones, it
stops at the end of each one with a `MILESTONE` line, and never starts the
next.

With `--exit-on-human` it also exits (code 4) when a lane publishes or fails,
for a harness that cannot report a background command's output as it arrives:
the command ending is the signal, and the agent runs it again. The
orchestrator starts the loop for you after the first launch.
