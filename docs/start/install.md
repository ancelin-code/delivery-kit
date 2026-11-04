# Install the Kit

The six skills are one workflow, not a catalogue you pick from. Each phase
consumes the file the previous phase wrote, so a single skill installed alone
is a phase with no input and no consumer. Install them together, into the
repository that holds the project's plan.

## Prerequisites

Each developer machine needs `git`, a POSIX `sh`, and `gh` 2.0 or later,
authenticated with `gh auth login` against the repository's forge. `gh` is not
optional: task branches are deleted on merge, so merged pull requests are the
only record of which tasks are done, and `status.sh` refuses to run without
them.

The helpers are POSIX `sh` and POSIX `awk`, so nothing else is installed: they
run on the `sh` of Linux, macOS and Alpine as they come, and CI runs them on
dash, BusyBox ash and macOS's own `sh`.

## Add the skills

Use the `skills` CLI. It installs all six skills, writes each one to
`.agents/skills/` and symlinks it into `.claude/skills/`, and records a
`skills-lock.json` so every developer restores the same version.

```sh
npx skills add https://github.com/ancelin-code/etabli/tree/main \
  --skill '*' -a claude-code -a github-copilot -y
```

The `/tree/main` suffix installs what has been released to `main`. Without it,
you get the default branch, `develop`, where unreleased work lands first.

To install a release instead of the tip of `main`, name its tag:
`…/etabli/tree/v0.1.0`. The lock file then records that version, and the
[Changelog](../changelog.md) lists what each one changed.

Add an `-a <agent>` for each other harness your team uses; `npx skills add
--help` lists the names it knows. Scope the agents with `-a`: plain `--all`
also writes a full third copy under `agent/` for the other agents it supports,
which a target repository does not need.

!!! warning "Keep an agent that reads `.agents/skills/`"

    Keep `-a github-copilot`, or another agent that reads `.agents/skills/`,
    even if your team uses only Claude Code. With `-a claude-code` alone, the
    CLI copies each skill into `.claude/skills/` and creates no `.agents/`. A
    later `npx skills update` then moves the skills it updates to
    `.agents/skills/` with links, and leaves the ones it finds up to date as
    copies. The kit's skills find each other as siblings, so that split install
    loses `etabli-implement`, and lanes would run without it.

    `where.sh` reports a split install as `NEXT repair-install`, and the
    launcher refuses to start. Installed with both agents, every skill is
    linked from the start and updates keep it that way.

Both directories matter: Copilot CLI reads `.agents/skills/`, while Claude Code
reads `.claude/skills/` and will not fall back. Installing by hand into only
`.agents/skills/` silently degrades every Claude Code lane.

Then commit what the CLI produced, including `skills-lock.json` and the
symlinks. Git stores symlinks natively, so **lanes running in worktrees get the
kit without a second install**. Everyone else restores the pinned versions
with:

```sh
npx skills experimental_install
```

## Make the orchestrator the default assistant

Then make the kit the project's default assistant, and commit `AGENTS.md`:

```sh
sh .agents/skills/etabli-orchestrator/scripts/install-routing.sh
```

It appends a short block to `AGENTS.md`, creating it if needed, that sends
every request about the project to `etabli-orchestrator`. Claude Code and
Copilot CLI both read that file on every request, so the kit is consulted even
when a question matches no skill description. Without it, a plain *"what's the
status of this project?"* reached no kit skill in either harness, and Copilot
answered from git alone, recommending a task already merged. The orchestrator
runs the same step itself the first time it finds the block missing.

## Choose review skills

The same script writes a starter `delivery/review-lenses.conf`, which is worth
committing too. When a task reaches review, the orchestrator reads this file to
suggest which review skill to run on its pull request. As shipped, it suggests
only the harness's own review. Edit it to map a concern to a review skill
installed in the project, optionally with the paths that bring that concern
in:

```text
# lens     skill             paths that bring the lens in
general    code-review
security   security-review   */auth/* *secret* *.tf
```

A task can also ask for a lens through its `review` field, and anyone can add
one to a pull request with a `review:<lens>` label. The full format is in the
[review lenses](https://github.com/ancelin-code/etabli/blob/main/.agents/skills/etabli-orchestrator/references/conventions.md#review-lenses)
convention. The script never overwrites an existing file.

## Check for shadowing skills

Slash invocation makes skill names part of the interface, so a personal skill
of the same name wins. On each developer machine:

```sh
copilot skill list          # inspect Personal skills
ls ~/.claude/skills         # and here
```

Disable anything that collides with an `etabli-*` name.

## Repair a split install

To repair a split install, remove every copy and install again:

```sh
rm -rf .claude/skills/etabli-* .agents/skills/etabli-*
npx skills add https://github.com/ancelin-code/etabli/tree/main \
  --skill '*' -a claude-code -a github-copilot -y
```

Re-running `npx skills add` with `-a claude-code` alone is not a repair: it
puts every skill back as a copy in `.claude/skills/`, and leaves the old
`.agents/skills/` directories behind to go stale.

Next: [Drive the Route](route.md).
