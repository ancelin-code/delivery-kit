# Plug a Connector

Git stays the only place where work is decided. Other tools, a Jira board for
management or Confluence pages for readers who never open the forge, get a
one-way copy of it: a **connector** reads the kit's state and makes the tool
match it. Connectors live in their own repositories, with their own
credentials and configuration, so the kit holds nothing tool-specific.

## The snapshot

The kit's side is one command. From the planning repository, it prints the
whole project as JSON: milestones, epics and what each delivers, tasks with
the state `status.sh` gives them, their repository and pull request, the
coverage of each requirement, and the planning documents.

```sh
sh .agents/skills/etabli-status/scripts/snapshot.sh
```

A connector reads that on stdin:

```sh
sh .agents/skills/etabli-status/scripts/snapshot.sh \
  | my-connector --config ~/shop.toml --dry-run
```

Each run compares the whole snapshot with the tool and applies the difference,
so it can run by hand, after each merge, or from a scheduled job, with the
same result. If the state cannot be derived, `snapshot.sh` prints nothing and
exits non-zero, so no connector acts on a guess.

## The connector contract

What a connector must and must not do is the contract in
[ADR-005](https://github.com/ancelin-code/etabli/blob/main/docs/decisions/ADR-005-external-tool-connectors.md).
In short:

- **One way only.** It writes to the tool and never to git.
- **Declared ownership.** It names the fields it owns and writes only those.
  In Jira, sprints, points, priority and assignee stay with people, and an
  issue moved into a sprint stays there.
- **Visible corrections.** A change to an owned field, such as a card dragged
  to another column, is put back on the next run, with a comment saying why.
- **Standard output.** `--dry-run` prints each change without making it. Exit
  `0` means the tool matches, `1` means a change failed, and `2` means the
  input or configuration was refused before anything was touched.

To write a connector for another tool, start from that contract and the
snapshot's `schema` number, and refuse any schema version the connector
doesn't know.
