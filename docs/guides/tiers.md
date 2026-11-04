# Choose Models with Tiers

Each task's `tier` says how much capability its work needs:

| Tier | For |
|---|---|
| `plan` | Design decisions, contracts, a task with interacting constraints |
| `build` | Ordinary execution against explicit acceptance criteria. The default |
| `chore` | Mechanical changes with no judgement in them |

A tier is a hint, not a model name. Établi cannot know which models your
account may use, so by default it passes no model at all and the harness
applies its own default.

## Map a tier to a model

To say what a tier means for you, write a `tiers.conf` at
`~/.config/etabli/tiers.conf`. The names below are examples:

```ini
[plan]
    harness = claude
    model = opus

[build]
    model = sonnet

[chore]
    harness = copilot
    model = gpt-6-luna
```

The file uses git's own config format, so comments and quoting work as they do
in `.gitconfig`. Harness and model are both optional. A mapping applies only to
the harness it names, so a model id never reaches a harness that would refuse
it.

A team that agrees on a mapping can commit it as `delivery/tiers.conf`; the
developer's own file wins, tier by tier. The full rules are in the
[conventions](https://github.com/ancelin-code/etabli/blob/main/.agents/skills/etabli-orchestrator/references/conventions.md#mapping-a-tier-to-a-model).

## Which harness a lane runs on

A lane runs on the first of: `--harness`, the harness its tier maps to,
`$DELIVERY_HARNESS`, then the first harness found installed. `--harness` moves
a whole launch on purpose, for example to the one whose allowance still has
room.

## The reviewer runs one tier up

A lane's refinement session runs one tier up: a `chore` task is reviewed as a
`build` one, a `build` task as a `plan` one, and a `plan` task by `plan`. With
the mapping above, a `build` lane is written by `sonnet` and reviewed by
`opus`, because a reviewer no stronger than the author finds little the author
would not. When the tier above maps to another harness, the review runs there,
which also gives the change a second model's view.

A tier can name its own `reviewer` instead, a model for the tier's own
harness:

```ini
[chore]
    harness = claude
    model = haiku
    reviewer = sonnet
```

## Watch the budget

Putting every task on `plan` is how a budget disappears, so review the tiers
when you approve a decomposition.

Model ids change with releases, and an account's plan decides which ones it
may use. A harness refuses an id it cannot use before any request, which costs
nothing, so check an id before it goes into a mapping. For Copilot CLI:

```sh
copilot -p "Reply OK." --model <id>
```
