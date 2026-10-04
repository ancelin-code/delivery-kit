# ADR-008: The helpers are POSIX sh, and data lives in files and awk

**Status:** accepted
**Date:** 2026-10-04

## Context

The helpers were bash 4.4: arrays, associative arrays, `[[ ]]`, `local`,
`pipefail`. That made them hard to read in the worst places, and it made them
hard to run: macOS ships bash 3.2, so every helper opened with a version guard,
CI installed a newer bash on macOS, and the README told each developer to
`brew install bash`. Alpine, BusyBox and many agent sandboxes have no bash at
all, and a tool that runs unattended agents is often run in exactly those.

`shellcheck --shell=sh` found 775 incompatibilities across the 12 helpers.
About 400 were mechanical (`[[ ]]`, `==`, `((..))`, `+=`). The rest were the
real change: arrays, associative arrays, here-strings and `pipefail`.

## Decision

**Every helper is POSIX `sh`, using only POSIX `awk`, `sed`, `grep` and the
other standard tools.** ShellCheck holds each script to POSIX through its
`#!/bin/sh` shebang, a test keeps the shebang from being swapped, and the whole
suite runs against dash (Ubuntu), macOS's own `sh`, and BusyBox ash and awk on
Alpine.

The patterns that replace the bashisms:

| Was | Is |
|---|---|
| Array of items | Newline-separated list in a variable, or a file with one entry per line |
| Associative array | A directory with one file per key (task ids and tiers are slugs), or a TSV file read with awk |
| Argument array passed on | `set --` to build the command, or the rotate idiom that checks each option once and queues it behind the rest |
| `[[ x =~ re ]]` | `case` patterns |
| `local` | A subshell function body, `f() ( ... )`, or a name no other code uses |
| `<<<` and `< <(cmd)` | A here-document, or a temporary file |
| Cross-checks over many tasks | One awk program (`validate-tasks.sh`) |
| `pipefail` | Not used. A failure that matters is checked where the command runs |

The repository's own tooling in `.mise/scripts/` stays bash: it runs under mise
on a machine that has set the repository up, not on a consumer's machine.

## Alternatives considered

- **Keep bash and document the requirement.** Rejected: the macOS guard, the
  `brew install bash` step and the missing bash on small images are a recurring
  cost for a benefit of nicer syntax.
- **Rewrite in Python or another language.** Rejected earlier, and still: it
  adds an interpreter to every machine and sandbox, and the helpers are glue
  around git and gh, where a shell is the natural tool.
- **A compiled single binary.** Rejected for now: it needs a release pipeline
  per platform and makes the helpers opaque to the agents that read them.

## Consequences

- No bash version guard, no guard tests, no macOS bash install in CI.
- Maps held in files are slower than a bash array, which does not matter at the
  size of a task set: a status read is dominated by `gh`.
- A contributor cannot reach for an array. The cost is paid once, in how the
  data is held, and ShellCheck says so before review does.
- Only POSIX awk is available, so `validate-tasks.sh` and the JSON escaping in
  `snapshot.sh` avoid gawk-only functions and `-v` assignments that read
  backslashes.
