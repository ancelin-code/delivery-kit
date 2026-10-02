# ADR-005: External tools are projections of git, fed by one snapshot

**Status:** accepted
**Date:** 2026-09-25

## Context

The kit keeps every delivery artifact in git and derives run state from refs
and pull requests: nothing stores status. Teams that adopt it still plan and
report in other tools, Jira first and Confluence second, and management reads
those, not the repository. Without a link, someone re-types the task set into
Jira by hand and the two drift from the first day.

Three constraints shape the answer:

- git stays the only source of truth; a second one would bring back the stored
  status the kit was built to avoid
- the kit targets any forge and any tracker, and holds no Atlassian detail, the
  same way it holds no harness-specific tool names
- CI has no runner today, so whatever syncs cannot assume a pipeline

Jira adds two things the kit has no notion of. Sprints are a human promise
about a period, and git has no information about them. And on an existing
codebase the epics already exist, usually broader and vaguer than a kit epic,
and belong to whoever wrote them.

## Decision

**The kit exports one snapshot; connectors outside the kit project it.**

### The snapshot is the interface

`fourmee-status` gains `scripts/snapshot.sh`, which prints the state of the use
case as one JSON document on stdout. It reads what `status.sh` already reads,
plus the task frontmatter and the epics of `delivery/decomposition.md`, and
writes nothing. It fails as `status.sh` does, printing nothing, rather than
report a guessed state. The document carries a `schema` number, raised on any
change a connector could break on; adding a field does not raise it:

```json
{
  "schema": 1,
  "use_case": {"repo": "shop-api", "commit": "6f1833d…"},
  "epics": [{"id": "ingestion", "delivers": "Every source document is loaded."}],
  "tasks": [{
    "id": "ingestion-003", "title": "Parse conref references", "type": "feat",
    "epic": "ingestion", "repo": "shop-api", "state": "in-review",
    "holder": "devA", "depends_on": ["ingestion-001"],
    "pull_request": "https://forge.example/org/shop-api/pull/42",
    "file": "delivery/tasks/ingestion-003.md"
  }],
  "documents": [
    {"kind": "requirements", "path": "delivery/prd.md", "title": "Shop requirements"},
    {"kind": "decision", "path": "delivery/decisions/ADR-001-storage.md", "title": "ADR-001: Storage"}
  ]
}
```

`state` takes the values `status.sh` derives: `blocked`, `ready`,
`in-progress`, `in-review`, `done`. A draft pull request is `in-progress`; a
task is `in-review` once its pull request is marked ready.

### A connector is any program that honours this contract

- **Input:** the snapshot on stdin, and the connector's own configuration.
  Configuration and credentials live with the connector, never in the planning
  repository.
- **Reconcile, not replay.** Each run compares the whole snapshot with the
  external tool and applies the difference. Running it twice changes nothing
  the second time, so the trigger does not matter: a local hook, a cron job, a
  function app or a pipeline all give the same result.
- **One-way.** A connector writes to the external tool and never to git.
- **Found by task id.** A connector finds its own items by the task id stored in
  the external tool (a Jira entity property or label), not by a mapping file in
  git, which every sync would otherwise have to commit.
- **Declared field ownership.** A connector names the fields it owns and writes
  only those. Every other field belongs to the people using the tool.
- **Drift is corrected visibly.** When someone changes an owned field, the next
  run restores it and leaves a comment saying why.
- **Forward only past its last owned status.** A connector moves an item up to
  the last status it owns and never pulls an item back from a later status that
  humans own.
- **Touches only what it created, or was told to adopt.** Existing items the
  configuration does not name are never read for changes, closed, or moved.
- **`--dry-run`** prints each change it would make, one per line, tab-separated:
  `CREATE`, `UPDATE`, `TRANSITION`, `LINK` or `COMMENT`, then the external key,
  the task id, and a detail. Without it the same lines report what was done.
- **Exit codes:** `0` when the tool matches the snapshot, whether or not
  anything changed; `1` on any failure, after reporting the changes already
  made; `2` on a usage or configuration error, before touching anything.

### Connectors live outside the kit

Each connector is its own repository, with its own dependencies, credentials
and release cycle. The kit ships the snapshot and this contract, and nothing
tracker-specific.

### The Jira connector, as the reference case

| Kit | Jira | Owner |
|---|---|---|
| Epic | Epic, or an adopted existing epic | kit when created; humans when adopted |
| Task | Story or Task under its epic | kit |
| Summary, description | title, and a link to the task file | kit |
| `state` | status, and so the board column | kit |
| `depends_on` | "is blocked by" links | kit |
| Pull request | remote link | kit |
| Sprint, points, priority, assignee, fix version | as is | humans |

Created issues start with no sprint, in the backlog. Moving one into a sprint is
a human decision the connector never reverts.

States map to statuses through the connector configuration, since every Jira
workflow differs. On a board with Backlog, Ready, In progress, In validation and
Done columns, where In validation means code review: `blocked` to Backlog and
flagged, `ready` to Ready, `in-progress` to In progress, `in-review` to In
validation, `done` to Done. When a workflow does not allow a direct transition,
the connector walks the allowed ones, filling any field a transition screen
requires from its configuration.

**Existing epics are adopted, not rewritten.** The connector configuration maps
kit epics to an existing Jira epic, several to one if needed. The connector
creates tasks under it and adds a remote link to the requirements, and never
edits the epic's own summary or description. An unmapped kit epic gets a new
Jira epic. A vague existing epic is input to `fourmee-spec`, which is where
its clarified form ends up.

**Jira is intake, never state.** A ticket can start work, as a request to
`fourmee`. From then on the work lives in git, and the connector
reports back to that ticket.

## Alternatives considered

- **Jira as the source of truth** - Rejected. Lanes, claims and dependencies are
  derived from git because that is what the lanes act on. A second store would
  have to be kept consistent with the refs, and a disagreement would have no
  owner.
- **Two-way synchronisation** - Rejected. Every field would need a merge rule,
  and a card dragged to In progress would have to mean something in git. It does
  not: a claim starts work, a card does not.
- **Event-driven updates from forge webhooks** - Rejected. They need a reachable
  endpoint and CI, which this setup does not have, and a missed event leaves
  permanent drift. Reconciling from a snapshot repairs itself on the next run.
- **The issue mapping stored in git** - Rejected. Every sync that creates an issue
  would commit, and the planning history would fill with sync noise.
- **Connectors shipped in the kit** - Rejected. It would bring tracker APIs,
  credentials and one team's workflow into skills meant to install anywhere.
- **A `jira` field in each task file** - Deferred. Jira's development panel links
  a pull request only when the issue key appears in it; the connector can add the
  key to the pull request through the forge API instead, which keeps git free of
  tracker identifiers. Reopen if that proves insufficient.
- **Mapping sprints** - Rejected. Git has no fact about a sprint to project.

## Consequences

Management gets its board from Jira, updated without anyone re-typing work, and
the team keeps one place where work is decided.

A connector restoring a card someone dragged will surprise people until the rule
is known: moving a card does not start work, claiming the task does. Teams
adopting a connector need that said once, up front.

A Jira board makes gaps between the backlog and what ships visible to everyone.
That is useful and it is also political; agree who acts on it before connecting a
large project.

Story points and velocity lose their meaning on kit tasks, since agent effort is
not human effort. Lead time from ready to merged, and the time a pull request
waits for review, are the measures that survive.

The snapshot schema is now a public interface. Changing a field connectors read
means raising `schema`, and connectors should refuse a version they do not know
rather than guess.
