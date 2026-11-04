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
npx skills add https://github.com/ancelin-code/etabli/tree/v0.1.0 --skill '*' -y
```

Naming a release tag, here `v0.1.0`, pins the install to it: the lock file
records that version, and the [Changelog](../changelog.md) lists what each
release changed. Replace the tag with the release you want, or install what has
been released to `main` with `/tree/main`. Without a `/tree/…` suffix you get
the default branch, `develop`, where unreleased work lands first.

Choose no agent: the CLI puts the skills in `.agents/skills/`, which Copilot CLI
and Codex read, and links them into `.claude/skills/` for Claude Code. On a
machine where it detects no agent installed, it also writes a copy under
`agent/`, which a repository does not need and you can delete.

Then commit what the CLI produced, including `skills-lock.json` and the
symlinks. Git stores symlinks natively, so **lanes running in worktrees get the
kit without a second install**. Everyone else restores the pinned versions
with:

```sh
npx skills experimental_install
```

!!! warning "Do not pass `-a claude-code` on its own"

    With `-a claude-code` alone, the CLI copies each skill into
    `.claude/skills/` and creates no `.agents/`. A later `npx skills update`
    then moves the skills it updates to `.agents/skills/` with links, and
    leaves the ones it finds up to date as copies. The kit's skills find each
    other as siblings, so that split install loses `etabli-implement`, and
    lanes would run without it. `where.sh` reports it as
    `NEXT repair-install`, and the launcher refuses to start; see
    [Repair a split install](#repair-a-split-install).

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

The script also writes a starter `delivery/review-lenses.conf`. It only matters
when you review pull requests; leave it as it is for now, and see
[Review the Pull Requests](../guides/review.md) when you want it.

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
npx skills add https://github.com/ancelin-code/etabli/tree/v0.1.0 --skill '*' -y
```

Re-running `npx skills add` with `-a claude-code` alone is not a repair: it
puts every skill back as a copy in `.claude/skills/`, and leaves the old
`.agents/skills/` directories behind to go stale.
