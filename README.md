# Établi

[![CI](https://github.com/ancelin-code/etabli/actions/workflows/ci.yaml/badge.svg?branch=develop)](https://github.com/ancelin-code/etabli/actions/workflows/ci.yaml)
[![Docs](https://github.com/ancelin-code/etabli/actions/workflows/docs.yaml/badge.svg?branch=develop)](https://ancelin-code.github.io/etabli/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Agent Skills for AI-native delivery: requirements and design spine,
decomposition, parallel implementation lanes, review. Git is the only state:
no server, no database, no status file. *Établi* is French for *workbench*.

The documentation is at <https://ancelin-code.github.io/etabli/>.

> **Status: early.** The kit is used on real projects, and `v0.1.0` is its first
> release. Conventions may still change between versions. Install a release
> tag, read [CHANGELOG.md](CHANGELOG.md) before updating, and expect breaking
> changes to be called out there rather than migrated.

**This repository is the kit.** The six Établi skills are one workflow,
not a catalogue you pick from. Each phase consumes the file the previous phase
wrote, so a single skill installed alone is a phase with no input and no
consumer. Install them together.

The skills hold no harness-specific tool names. The lane launcher has adapters
for Claude Code, GitHub Copilot CLI, Codex CLI, OpenCode and Pi, and a custom
command for any other, so no single vendor's license is required.

## Quickstart

Each machine needs `git`, a POSIX `sh`, and an authenticated `gh` 2.0 or
later. In the repository that holds the project's plan:

```sh
npx skills add https://github.com/ancelin-code/etabli/tree/v0.1.0 --skill '*' -y
sh .agents/skills/etabli-orchestrator/scripts/install-routing.sh
```

Commit what that produced, then tell the orchestrator what you want built:

```text
/etabli-orchestrator <what to build>
```

It writes the requirements, then the tasks, and stops at each for your
approval; then lanes build the tasks and open draft pull requests. The
[documentation](https://ancelin-code.github.io/etabli/) covers the install, the
route, lanes, tiers, harnesses, several repositories, reviews and connectors.

## Develop

```sh
mise run dev     # local environment and git hooks
mise run lint    # ruff, shellcheck, rumdl, actionlint, Vale, skillcheck, security scan
mise run test    # behavioural tests
mise run docs:serve  # the documentation site, rebuilt on each change
```

### Contributing

Issues and pull requests are welcome. Read [AGENTS.md](AGENTS.md) first: it
holds the rules every change is checked against, above all that a rule stays in
the kit only if removing it measurably degrades results.

- Branch from `develop` and open the pull request against it. Pull requests are
  squash-merged, so the title is a Conventional Commits line.
- `main` holds released work only. It moves forward by merging `develop` into
  it, and every release tag `vX.Y.Z` is cut on it.
- Both branches are protected. A change reaches them only through a pull
  request whose `lint` and `test` checks pass on Linux, macOS and Alpine.
  Neither branch can be force-pushed or deleted, and a release tag cannot be
  moved or deleted.
- Work done with an agent is labelled `ai-assisted`; see
  [AGENTS.md](AGENTS.md#pull-requests).
- Each test marks its steps with `# Given`, `# When` and `# Then` comments; see
  [AGENTS.md](AGENTS.md#validation).

## Maintenance

Every rule in this kit that works around harness behaviour was earned by a test,
and harness behaviour changes. The tests, and the CLI versions they were run
against, are recorded in [docs/harness-validation.md](docs/harness-validation.md).

Re-run them after a Claude Code or Copilot CLI upgrade, and delete any rule that
no longer earns its tokens. Both CLIs update themselves silently, so nothing
announces the moment to do this: compare the recorded versions against
`claude --version` and `copilot --version` before a run that matters.

Two rules are worth re-checking first, because both fail quietly rather than
loudly:

- the `.claude/skills/` symlinks, which exist only because Claude Code did not
  register `.agents/skills/`. Harmless if that changes, but dead weight.
- slash-command invocation of a skill. If a harness stops resolving
  `/etabli-implement <task-file>` as an invocation, every lane reverts to
  reading the skill as prose, which makes its boundaries advisory and leaves no
  trace in the lane log.

This is a maintainer's task, not part of a run. It is deliberately not in any
`SKILL.md`, so no agent pays tokens for it on every invocation.

## Design

The route, the gates and the lane policy live in the `etabli-orchestrator`
skill. Shared conventions - the project, epic and task units, placeholders,
task schema, branch names, the claim protocol, tiers, pull request rules -
are in its `references/`, loaded on demand during a run.

Everything an agent does not need at run time stays out of the skills and lives
in `docs/`: the user documentation site, built with Zensical from
`zensical.toml`, and two maintainer records kept out of the site, the record of
which harness assumptions were tested and what the tests found, and
`docs/decisions/` for the choices whose reasons are not recoverable from the
code. Skills carry rules; `docs/` carries the evidence for them.

## License

Apache-2.0. See [LICENSE](LICENSE).
