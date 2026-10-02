# Agent Instructions for the fourmee repository

This repository holds the AI-native **Fourmee**: a family of Agent Skills
that route a use case from requirements through parallel implementation lanes to
draft pull requests.

The kit is exploratory. Prefer deleting a rule over defending it.

## Project overview

- Skills live in `.agents/skills/<skill-name>/SKILL.md`
- Shared conventions live in `.agents/skills/fourmee/references/conventions.md`
- Validated harness assumptions live in `docs/harness-validation.md`, a
  maintainer record that ships with the repository and not with the skills
- Keep skills small, reviewable, and focused on one reusable capability

## Repository structure

- `.agents/skills/<skill-name>/SKILL.md`: skill entrypoint
- `.agents/skills/<skill-name>/references/`: detail loaded on demand
- `.agents/skills/<skill-name>/scripts/`: deterministic helpers, non-executable
- `docs/`: maintainer records, not installed with the skills and not loaded at
  run time
- `docs/decisions/`: numbered decision records, `ADR-<nnn>-<slug>.md`
- `tests/unit/`: behavioural tests driving the bash helpers
- `.mise/scripts/`: repository validation helpers
- `.github/workflows/`: CI

## The rule that governs this kit

A skill must **beat vanilla harness behavior** on its task, or be free. A rule
appears only if removing it measurably degrades results. This kit exists because
a previous skill lost to an unassisted harness by adding ceremony the model did
not need.

Concretely:

- do not re-describe generic git, GitHub, or code-review competence
- do not add approval gates that duplicate harness permission modes
- deterministic, non-reasoning steps belong in bash, not in prose
- no harness-specific tool names: the kit must work in Claude Code and in
  GitHub Copilot CLI

## Authoring rules

- `SKILL.md` stays at or below 500 lines and 5,000 tokens; references load on demand
- Keep helper scripts non-executable and invoke them as `bash <skill-root>/scripts/...`
- The Fourmee skills (`fourmee` and `fourmee-*`) are one workflow installed whole, not independent
  units: a phase consumes the file the previous phase wrote. Still never
  reference a sibling skill by file path, only by name, so each stays
  individually evaluable and relocatable
- The placeholder convention this implies (`<skill-root>` vs. naming a sibling
  skill) is defined once, in the shipped
  [delivery conventions](.agents/skills/fourmee/references/conventions.md#placeholders),
  since this file does not install with the kit. Point new skill content at
  that definition rather than restating it here or anywhere else
- Every skill is mirrored as a relative symlink under `.claude/skills/`. Adding a
  skill means adding its symlink, or Claude Code cannot invoke it by slash
  command. This matches the layout `npx skills add` produces in a consuming
  repository, so the kit's own checkout and an installed copy behave the same
- Frontmatter requires `name`, `author`, `description`, `license`, `repository`,
  `product-version`, `version`, `keywords`, `spec-version`, `metadata.category`,
  and `metadata.owner`

## Validation

- `mise run lint` runs ruff, shellcheck, rumdl, actionlint, Vale, skillcheck,
  the helper-mode check, and the skill security scanner
- `mise run test` runs the behavioural test suite
- The kit's helpers are bash and are covered behaviourally, so no coverage gate
  is applied. Add one if Python source ever lands here.
- Re-run the checks in `docs/harness-validation.md` after any harness upgrade,
  and delete any rule that no longer earns its tokens

CI runs `mise run lint` and `mise run test` on every push and pull request.
The **pre-push hook** installed by `mise run dev` runs the same tasks locally,
so a failure shows up before anything is shared. Do not bypass it with
`--no-verify`. Reference every action by its full commit SHA, with the version
in a trailing comment; Dependabot keeps both current. Tests run on Linux and
macOS, lint on Linux only.

## Pull requests

Pull requests that agents worked on carry the `ai-assisted` label. A workflow
adds it when a commit has a `Co-authored-by` or `Assisted-by` trailer naming an
agent, when the template's AI box is ticked, or when an agent's own account
opened the pull request. Do not add a "generated with" line to a description:
the label says it.
