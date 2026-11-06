# ADR-012: The kit supports GitHub only, for now

**Status:** accepted
**Date:** 2026-11-06

## Context

Claims are pure git: a create-only push of `task/<id>` works on any forge. What
git alone cannot say is which tasks are done, because task branches are deleted
on merge and only the merged pull request keeps the record. Four helpers ask
the forge through `gh`:

- `status.sh` and `snapshot.sh` list pull requests per task branch, to derive
  `in-review` and `done`.
- `where.sh` reads a pull request's number, labels and changed files, to choose
  its review lenses.
- `publish-lane.sh` opens the draft pull request and labels it.

Other forges (GitLab, Bitbucket, Forgejo, Azure DevOps) have the same concepts
under other names and other CLIs. The kit has only ever run against GitHub.

## Decision

The kit requires GitHub and `gh` 2.0 or later, and says so in the README and the
installation page. Making the forge replaceable is planned for a later version.

## Alternatives considered

- **A forge adapter now, on the model of `harness.sh`.** Rejected for this
  release: it would be written against one forge and guessed for the others. The
  harness adapters are only trustworthy where a lane ran on the real CLI
  ([ADR-008](ADR-008-harness-adapters.md)); a forge adapter nobody has run is
  worse, because its failure is a wrong answer to "is this task done".
- **Derive "done" from git alone**, by keeping task branches after the merge, or
  tagging `done/<id>`. Rejected for now: it changes the claim protocol and
  clutters the remote, and the pull request is the record people already trust.
- **Per-forge scripts copied from the GitHub ones.** Rejected: four helpers
  would fork into one set per forge.

## Consequences

- A project on another forge cannot use the status, follow and publish helpers.
  The skills that only read and write files under `delivery/` still work.
- The seam for later is narrow, which is why waiting costs little: four
  questions put to the forge, namely the pull request of a branch and its state,
  its labels and changed files, opening a draft pull request, and adding a
  label. They would move into one `forge.sh`, as everything harness-specific
  lives in `harness.sh`, and nowhere else.
- Until then, new code calls `gh` only from those helpers, so the skills never
  depend on it and the work stays confined to a few files. The skills name it
  only to state the requirement.
