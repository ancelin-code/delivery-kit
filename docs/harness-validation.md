# Harness validation

Results of the early tests that gate the kit's design. Each test exists to
invalidate one assumption cheaply, before anything is built on top of it.

This is a record for maintainers, not a document any skill loads at run time.
Every conclusion that changes behaviour is already encoded where it acts: the
install steps and the shadowing check in the README, the claim rule in the
orchestrator's `conventions.md`, the symlink rule in `AGENTS.md`, the slash
invocation in the lane launcher, and the orchestrator's description, `where.sh`
and routing block. What is kept here is the evidence behind them.

These results are true of the versions below and of nothing else. When to re-run
them is in the README, under Maintenance.

Environment at time of testing (2026-09-21, test 4 on 2026-09-22, tests 5 to
8 on 2026-09-23):

| Component | Version |
|---|---|
| Claude Code | 2.1.278 (2.1.280 for test 5) |
| GitHub Copilot CLI | 1.0.86 (1.0.87 for test 4, 1.0.88 for test 5) |
| git | 2.34.1 |

## Support matrix

One column per harness, one row per assumption the launcher makes. A cell says
what was done and when. **Run** means observed on the real CLI. **Help** means
read from the installed CLI's own `--help` or `debug` output. **Docs** means
read from the vendor's documentation and not run, because there is no license to
run it. Only *Run* cells justify calling a harness validated.

| Assumption | Claude Code | Copilot CLI | Codex CLI | OpenCode 1.18.18 | Pi |
|---|---|---|---|---|---|
| Takes a prompt with no terminal | Run, 2026-09 | Run, 2026-09 | Docs, 2026-10-04: `codex exec` | Help, 2026-10-04: `opencode run` | Docs, 2026-10-04: `-p` |
| Model flag | Run, 2026-09 | Run, 2026-09 | Docs: `--model` | Help: `--model provider/model` | Docs: `--model` |
| Access to the planning checkout | Run, 2026-09: `--add-dir` | Run, 2026-09: `--add-dir` | Docs: `--add-dir` | None; `--auto` is expected to cover it | Not needed, no sandbox |
| Acts with nobody to approve | Run, 2026-09: `acceptEdits` and `--allowedTools Bash` | Run, 2026-09: `--allow-all-tools` | Docs: `--sandbox workspace-write` | Help: `--auto`, which approves what the config does not deny | Docs: asks nothing |
| Denies `terraform apply` and `destroy` | Run, 2026-09 | Run, 2026-09 | Not denied; the sandbox has no network | Help, 2026-10-04: inline config is read (`opencode debug config`); denial not run | Cannot |
| `--no-web` | Run, 2026-09 | Run, 2026-09 | Nothing to take away | Help, 2026-10-04: `webfetch` deny reaches the resolved config; not run | No web tool |
| Resolves `/<skill>` in a prompt | Run, 2026-09 | Run, 2026-09, in the skills repository only | Not used | Not used | Not used |
| Lists the kit's skills in a worktree | Run, 2026-09 | Run, 2026-09 | Unknown | **Observed 2026-10-04: 0 of 5 listed** by `opencode debug skill` on the symlinked layout | Docs: reads `.agents/skills` |
| A real lane opens a draft pull request | Run, 2026-09 | Run, 2026-09 | Not run | Not run | Not run |

The launcher does not depend on a harness listing the skills: it tells every
harness except Claude Code, and Copilot CLI in the skills repository, to read
the skill file by path. That is what OpenCode's row led to.

Cursor CLI was considered for the fifth place. Its headless mode is `agent -p`
with `--force`, but its documentation does not say whether it reads `AGENTS.md`
or Agent Skills, and nothing could be run, so Pi was taken instead.

Sources read on 2026-10-04: the Codex non-interactive documentation, the Pi
package page and field guides, the Cursor headless documentation, and OpenCode's
skills documentation.

## Summary

| # | Assumption under test | Result |
|---|---|---|
| 1 | `copilot -p` discovers and loads skills from `.agents/skills/` inside a git worktree | Confirmed |
| 2 | `claude -p` runs a lane in a worktree, and tool deny rules are enforced | Confirmed |
| 3 | A create-only push of `task/<id>` is a sound claim lock | **Refuted as specified.** Fixed by the claim commit |
| 4 | Both harnesses accept `/<skill> <args>` as a `-p` prompt, from `.agents/skills/` | **Half refuted.** Confirmed for Copilot CLI; Claude Code needs `.claude/skills/`, fixed by symlinks |
| 5 | A plain "what's next" or "what's the status" reaches the kit and gets a correct answer | **Refuted.** 1 of 4 routed, Copilot answered wrongly twice. Fixed by the description, `where.sh`, and a routing block in `AGENTS.md` |
| 6 | A Claude Code lane under `--permission-mode acceptEdits` can run the repository's validation commands | **Refuted.** Every shell command is denied in `-p` mode. Fixed by `--allowedTools Bash`, with the deny rules still winning |
| 7 | Copilot CLI accepts the model names the launcher passes | **Refuted** for every label but `terra`: `Model "luna" from --model flag is not available`. Fixed by a per-harness model id, taken from the `/models` picker. Superseded: the launcher no longer carries ids, see [ADR-007](decisions/ADR-007-capability-tiers.md) |
| 8 | Lanes can reach the web, and `--no-web` takes it away on both harnesses | **Half refuted.** Copilot lanes always had it; Claude lanes never did. Fixed by allowing it on Claude, and by an off switch on both |
| 9 | A lane started in another repository loads the kit's skills from the planning repository through `--add-dir` | **Half refuted.** Confirmed for Claude Code; Copilot CLI loads only an added directory's `.github/skills/`. Fixed by naming the skill file in a Copilot lane's prompt |

## 1. Skill discovery inside a worktree

Both harnesses reach a kit copy in the worktree, not only in the main checkout.
This is what allows one kit copy per repository to serve every lane.

Read this together with test 4, which narrows the result: Copilot CLI registers
`.agents/skills/` as project skills, while Claude Code registers `.claude/skills/`
and reaches `.agents/skills/` only by reading the file directly.

Method: a throwaway repository with a canary skill in `.agents/skills/`, a
worktree added on a task branch, then discovery and loading checked from inside
the worktree. The canary returns a token the model cannot otherwise know, so a
correct answer proves the skill body reached the model rather than only its
name appearing in a listing.

`copilot skill list` reports the canary under `Project skills`, and `copilot -p`
returns the token. Listing alone is not sufficient evidence; check both.

**Operational consequence.** `copilot skill list` also reports `Personal skills`
from `~/.copilot/skills/` and `~/.agents/skills/`. Developer machines carry
personal copies of skills that compete with the kit for the same triggers, and
an older personal copy of a kit skill will shadow the intended behavior in ways
that are hard to see from inside a session. Day 0 preparation must inventory
personal skills on each machine and disable the conflicting ones.

## 2. Deny rules

`claude -p` loads the same `.agents/skills/` path and honors
`--disallowedTools`. A denied command is refused by the harness before it runs.

Method matters here. A model asked to run a destructive command often refuses on
its own judgment, which looks identical to an enforced deny in the transcript
and proves nothing about the harness. Separate the two by denying a command the
model has no reason to refuse, and by running the allowed case as a control:

- denied: the harness reports the permission denial, and the command does not run
- allowed, same command: the command runs

Only the paired result demonstrates enforcement. Model caution is not a control.

## 3. The claim lock

The specified claim was a create-only push of the task branch:

```sh
git push --force-with-lease=refs/heads/task/<id>: origin HEAD:refs/heads/task/<id>
```

This is atomic only while the ref does not exist. Every lane starts from the
same base commit, so once the winner's push lands, a second developer pushing
that same commit to that same ref is a no-op: git answers `Everything
up-to-date` and **exits 0**. The second developer's tooling reads success and
starts work on a task somebody else already holds.

The simultaneous race is the case that appears to work, because the ref genuinely
does not exist when both pushes are negotiated and the loser is rejected with
`cannot lock ref: reference already exists`. The failure appears in the ordinary
case instead: a developer picking the task up minutes later.

**Fix.** Push a commit that differs from every other developer's, so git cannot
resolve the push as a no-op. The claim commit provides that difference and
records who claimed the task and when:

```sh
git commit-tree "$tree" -p "$head" -m "chore(claim): task <id> [<claimant>]"
```

Building it with `git commit-tree` leaves local refs untouched until the claim is
won, so a lost race needs no cleanup.

Two properties follow, both of which the design wanted anyway:

- the holder and claim time are readable from `git log -1 task/<id>`, so status
  needs no shared mutable state file
- the commit message satisfies Conventional Commits and contributes nothing to
  the pull request diff

Covered by the claim tests under `tests/unit/`, which assert the simultaneous
race, the late claim, a free claim, and holder identity.

## 4. Invoking a skill as a slash command

The lane launcher used to pass a paragraph of prose naming the skill. That is a
suggestion, not an invocation: the model is free to interpret it, and in one
observed run it read `SKILL.md` as an ordinary file and followed it without the
skill ever being registered. The instructions then compete with the task text
for attention, and the skill's own boundaries are advisory.

Assumption under test: `-p "/<skill-name> <args>"` invokes the skill properly in
both harnesses, letting the launcher pass a task path and nothing else.

Method: a throwaway repository with a canary skill whose only instruction is to
write a proof file containing an argument it can only have received through the
invocation. The proof file distinguishes a real invocation from a plausible
answer, the same control used in tests 1 and 2.

| Harness | Skill in `.agents/skills/` | Skill in `.claude/skills/` |
|---|---|---|
| Copilot CLI 1.0.87 | Invoked, reported as `skill(fourmee-implement)` | not applicable |
| Claude Code 2.1.278 | **Not registered**, `/fourmee-implement isn't installed in this session` | Invoked, proof file correct |

Claude Code's failure is explicit and safe: it refuses the unknown command and
says so, rather than improvising. It does not fall back to `.agents/skills/`.

Asked in prose instead, Claude Code answered: *"The skill lives at
`.agents/skills/` (not the standard `.claude/skills/` location), so it wasn't
auto-registered with the Skill tool. I read its `SKILL.md` directly."* The work
got done, which is exactly why the earlier prose-based test looked like a pass.
A skill read as a file is indistinguishable from a skill invoked, until the
instructions are ones the model would rather not follow.

**Fix.** Keep the canonical copy in `.agents/skills/` and commit
`.claude/skills/<name>` as a relative symlink to it. Git stores symlinks natively
(mode `120000`), so worktrees and clones reproduce them, and both harnesses see
the same single source. Verified: the symlinked skill is invoked by slash command
in Claude Code, including from inside a worktree.

This is not a workaround invented here. The `skills` CLI
(`npx skills add <repo>`) produces exactly this layout - real directories under
`.agents/skills/`, relative symlinks under `.claude/skills/` - and is the
supported way to create it. Verified against this repository: installing into a
throwaway target, committing the result, and adding a worktree reproduces every
symlink with its target resolving.

**Operational consequence.** A repository adopting the kit installs it with that
CLI and commits what it produces. Hand-copying only `.agents/skills/` silently
degrades every Claude Code lane to prose interpretation.

**Installer note.** `--all` is shorthand for every skill and every agent, and
also writes a full copy under `agent/` for the other agents the CLI supports.
Scope it with repeated `-a` flags (`-a claude-code -a github-copilot`); a
comma-separated list is rejected even when each name is valid.

**Second consequence.** Slash invocation makes skill *names* part of the
interface. A personal skill with the same name shadows the kit's, which makes the
`fourmee` prefix a correctness measure and not only a readability one.

## 5. Routing plain questions to the kit

The kit is meant to be the project's assistant, so a developer asking in their
own words has to reach it. Nothing had tested that: every earlier test invoked a
skill by name.

Assumption under test: *"what should we do next?"* and *"what's the current
status of this project?"*, asked with no skill named, load `fourmee`
and produce a correct answer.

Method: a throwaway repository with the kit installed by symlink, as the
`skills` CLI lays it out, stopped partway through a run. Requirements, a
contract and the decomposition are approved, and the decomposition says
`Run as: serially`. `mapping-001` is merged with its branch deleted, `mapping-002`
is claimed by another developer, `export-001` is ready, `export-002` is blocked.
A fake `gh` reports the merge. Each question ran once per harness, headless,
with the tool calls recorded.

The fixture makes a wrong answer visible: git alone cannot tell a merged task
whose branch was deleted from one never started, and the serial run rules out
starting the ready task while another is in flight. The correct answer is to
wait for `mapping-002`, then take `export-001`.

Before, with the kit as it was:

| Harness | Question | Routed to | Answer | Cost |
|---|---|---|---|---|
| Claude Code | next | `fourmee` | correct | 9 turns, $0.35 |
| Claude Code | status | **no skill**; found `fourmee-status/SKILL.md` with `find` and read it as a file | correct | 6 turns, $0.25 |
| Copilot CLI | next | **no skill** | **wrong**: start `mapping-001`, already merged | 93k tokens in |
| Copilot CLI | status | **no skill** | **wrong**: "no implementation has started", Sam's claim missed | 120k tokens in |

Adding a routing paragraph to the fixture's `AGENTS.md` routed all four to the
orchestrator and made every answer correct, but each still spent four to six
tool calls locating `fourmee-status` and deriving state by hand, up to 160k
input tokens on Copilot.

**Fix.** Three changes, each aimed at one of the gaps:

- the orchestrator's description names status, progress, "what's next" and who
  is working on what, rather than only "which delivery phase comes next"
- `where.sh` reads every phase's approval, the run mode and the task state in
  one call, and prints the next action, so nothing is derived by hand
- `install-routing.sh` appends the routing block to the project's `AGENTS.md`,
  which both harnesses read on every request; Claude Code reads it when there
  is no `CLAUDE.md`, so no second file is needed

After, the same fixture and questions:

| Harness | Question | `AGENTS.md` block | Routed to | Answer | Cost |
|---|---|---|---|---|---|
| Claude Code | next | yes | `fourmee`, then `where.sh` | correct | 4 turns, $0.19 |
| Claude Code | status | yes | `fourmee`, then `where.sh` | correct | 4 turns, $0.19 |
| Claude Code | status | no | `fourmee`, then `where.sh` | correct; installed the block | 5 turns, $0.22 |
| Copilot CLI | next | yes | `fourmee`, then `where.sh` | correct | 80k tokens in |
| Copilot CLI | status | yes | `fourmee`, then `where.sh` | correct | 80k tokens in |
| Copilot CLI | status | no | `fourmee`, then `where.sh` | correct; told the user to install the block | 80k tokens in |

The description alone was enough to route both questions on both harnesses in
this run. The routing block is kept anyway: a description is matched against
the request, and the block is what still applies to requests no description
anticipates. It costs one paragraph. One Copilot answer miscounted the tasks as five
while listing the correct four, a slip in its prose rather than in the state
it read.

One run per cell is evidence, not a rate. Re-run the matrix after changing the
orchestrator's description, and after any harness upgrade.

## 6. Running validation in an unattended Claude Code lane

Test 2 proved that a denied command is refused. It did not prove that an
allowed one runs, and a lane that cannot run the repository's tests or its own
skill's helper scripts reports every criterion as unverified at best.

Assumption under test: `claude -p` with `--permission-mode acceptEdits`, as the
launcher started Claude lanes, can run a shell command.

Method: the same paired control as test 2, in throwaway repositories, on
Claude Code 2.1.280 with `haiku`. The model is asked to write a proof file with
one `python3 -c` command and nothing else, so the file exists only if the shell
tool ran. `--output-format json` exposes `permission_denials`, which separates
a harness refusal from a model that declined on its own.

| Flags beyond `-p` | Proof file | `permission_denials` | Model's answer |
|---|---|---|---|
| `--permission-mode acceptEdits` | absent | `Bash` | asks for an approval nobody is there to give |
| `acceptEdits --allowedTools 'Bash(python3:*)'` | present | none | done |
| `acceptEdits --allowedTools Bash --disallowedTools 'Bash(python3:*)'` | absent | `Bash` | denied |
| `acceptEdits --allowedTools Bash --disallowedTools 'Bash(terraform apply:*)'` | present | none | done |

`acceptEdits` approves file edits, not commands, and `-p` has no one to ask, so
the request is denied and the session still exits 0. Nothing in a text-mode log
marks the difference between a lane that validated and one that could not.

**Fix.** The launcher passes `--allowedTools Bash` to Claude lanes, which matches
the reach `--allow-all-tools` gives Copilot lanes. The third row is the one that
matters for safety: a deny rule still wins over the broad allow, so the
`terraform apply` and `terraform destroy` denies hold.

**What else a lane can reach.** A second probe, with the launcher's exact flags,
asked the model to try each tool once. Read, Write, Edit, Bash and subagents ran.
The harness denied three calls: `WebFetch`, `WebSearch`, and a Write outside
the worktree. The lane cannot read documentation from the web; everything it
builds against has to be in the repository or its contracts. The outside write
is the isolation working, though Bash is not held to it.

**Consequence for reading old logs.** Every Claude lane launched before this
fix ran without a shell: the repository contract detector, the tests and the
linters were all refused.

## 7. Model names on Copilot CLI

The launcher passed the kit's label, `sonnet` or `luna`, straight to
`copilot --model`. Copilot CLI 1.0.88 refuses it before the session starts:

```text
Error: Model "luna" from --model flag is not available.
```

Only `terra` had been mapped to a real id, `gpt-5.6-terra`. Every other Copilot
lane, including a portable label falling back from a missing `claude`, died at
startup with its claim held.

**Fix.** The launcher resolves the label per harness, after any fallback: Claude
Code takes the bare tier name, Copilot CLI its own id.

**Where the ids come from.** Not from `copilot help config`: its `model` list is
stale, and two of its ids, `gpt-5.6-luna` and `claude-opus-5`, are refused as
not available. The source is the `/models` picker in an interactive session,
which showed *GPT-6 Luna* and *Claude Opus 5.5*. An unavailable id fails before
any request, so probing costs nothing: `copilot -p "Reply OK." --model <id>`.
On 2026-09-23:

| Label | Copilot id | Credits for a one-word reply |
|---|---|---|
| `luna` | `gpt-6-luna` | 0.17 |
| `haiku` | `claude-haiku-4.5` | 2.11 |
| `terra` | `gpt-5.6-terra` | 3.42 |
| `sonnet` | `claude-sonnet-5` | 5.7 |
| `opus` | `claude-opus-5.5` | 11.17 |

A lane on an id the account cannot use exits at once, having changed nothing;
the launcher then releases its claim.

**Superseded on 2026-10-02.** The launcher no longer holds model ids, and the
table above is a dated record, not a mapping the kit ships. A tier names a model
only when a developer's `tiers.conf` does, and a mapping names the harness it is
for, so an id never reaches a harness that would refuse it. That is this
finding's lesson kept as a rule. The probe above still checks an id before it
goes into a mapping; see [ADR-007](decisions/ADR-007-capability-tiers.md).

## 8. Web access in a lane

Test 6 found Claude lanes denied `WebFetch` and `WebSearch`. The question was
whether Copilot lanes were the same, and how to switch web access on and off
on each side.

Method: a model asked to fetch
`https://docs.python.org/3/library/unittest.html` with its web tool and nothing
else, headless, with the lane's flags. `example.com` answered 403 from this
network whatever the flags, so it cannot tell a refusal from a failure; a
documentation site can.

| Harness | Flags beyond the lane's | Result |
|---|---|---|
| Claude Code | none | refused: `WebFetch` in `permission_denials` |
| Claude Code | `--allowedTools ... WebFetch WebSearch` | page title returned |
| Copilot CLI | none (`--allow-all-tools`) | page title returned |
| Copilot CLI | `--deny-tool web_fetch` | page title returned: the name is ignored silently |
| Copilot CLI | `--excluded-tools web_fetch` | fell back to `web_search` from the GitHub MCP server |
| Copilot CLI | `--excluded-tools web_fetch web_search` | `Disabled tools: web_fetch, web_search`; no web |

`--allow-all-urls` made no difference to the fetch in `-p` mode. The tool names
come from `--output-format json`, where Copilot reports `toolName`.

**Fix.** Web access is on by default on both sides, and `--no-web` on the
launcher takes it away: an explicit `--disallowedTools WebFetch WebSearch` on
Claude Code, since a developer's own settings may allow them, and
`--excluded-tools web_fetch web_search` on Copilot CLI.

**Security.** Fetched content is untrusted input to an unattended session that
has a shell and git credentials, which makes web access a prompt-injection path.
That is why it can be switched off, and why the choice is left to whoever
launches. `--no-web` narrows the path rather than closing it: the shell can
still reach the network.

## 9. Skills from an added directory

A use case spread over several repositories keeps the kit and its plan in one
of them. A lane working in another repository gets the planning one with
`--add-dir`. The question was whether a slash invocation then finds the kit's
skills there.

Method: two fresh repositories side by side, `home` holding a `probe-skill`
in `.agents/skills/` with its `.claude/skills/` symlink, and `code` holding
nothing. From `code`, headless, `/probe-skill hello` with `--add-dir ../home`,
on Claude Code 2.1.281 (`haiku`) and Copilot CLI 1.0.88 (`claude-haiku-4.5`).

| Harness | Skill directories in `home` | Result |
|---|---|---|
| Claude Code | `.agents/skills/`, `.claude/skills/` | skill ran: `PROBE-OK-7731 hello` |
| Copilot CLI | `.agents/skills/`, `.claude/skills/` | not found: "I don't see a skill named ..." |
| Copilot CLI | plus `.github/skills/` | skill ran |
| Copilot CLI | `.agents/skills/`, prompt "Read `<path>/SKILL.md` and follow it as a skill, with the arguments: hello" | skill ran |

`copilot --help` says as much: `--add-dir` loads that directory's
`.github/skills`, while `.agents/skills/` is only read from the working
directory's repository.

**Fix.** A lane in another repository gets `--add-dir <planning repository>` on
both harnesses, for the task file, contracts and decisions. Claude Code keeps
the slash invocation. Copilot CLI is told to read
`fourmee-implement/SKILL.md` by absolute path and follow it, which needs no
extra install in any repository.
