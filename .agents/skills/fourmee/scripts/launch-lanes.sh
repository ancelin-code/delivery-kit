#!/usr/bin/env bash
set -euo pipefail

# Fail early and clearly on an older bash, such as the 3.2 macOS ships.
if ((BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4))); then
  printf 'ERROR\tbash 4.4 or later is required, found %s\n' "$BASH_VERSION" >&2
  exit 1
fi

# Start one lane per task: a git worktree, a claim, and a headless agent session
# that ends in a draft pull request.
#
# Task ids come from the arguments, or from stdin when none are given, so this
# composes with whatever decided the tasks were ready:
#
#   bash status.sh --ready | awk '$1=="TASK" {print $2}' | bash launch-lanes.sh
#
# This script does not decide readiness. It decides how many lanes run, that two
# conflicting tasks never run together, and that a lane only starts on a task
# this machine actually won the claim for.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: bash launch-lanes.sh [options] [task-id...]

Starts a lane per task id, reading ids from stdin when none are given. A task
with a repo field gets its worktree, claim and pull request in that clone,
beside this repository; the lane reads its task file and contracts here. A lane
whose session exits cleanly is published as a draft pull request by
publish-lane.sh; one whose session fails without leaving work behind gives its
claim back through release-lane.sh. Both sit beside this script.

Options:
  --max-lanes <n>       Most lanes to run at once (default: 3).
  --harness <name>      claude, copilot, or auto (default: auto, by model label).
                        auto falls back to whichever harness is installed for
                        opus/sonnet/haiku tasks, so a Copilot-only machine
                        needs no Anthropic license.
  --effort <level>      Override the effort of every task in this batch: low,
                        medium, high, xhigh or max. Defaults to each task's own
                        effort field, or medium where it has none.
  --tasks-dir <dir>     Directory holding <id>.md task files (default: delivery/tasks).
  --worktree-root <dir> Directory that receives one <task-id> worktree per lane.
                        Defaults to $FOURMEE_WORKTREE_ROOT when set, else to
                        ../lanes/<name of this repository>.
  --log-dir <dir>       Where session logs are written (default: .lanes/logs).
  --no-web              Take web fetch and web search away from the lanes.
                        SECURITY: web access is on by default, and it is a
                        prompt-injection path. A lane runs unattended with a
                        shell and your git credentials, and a fetched page is
                        text the model may follow. Use --no-web when lanes
                        should build from the repository and its contracts
                        alone. The shell can still reach the network.
  --claim-script <path> claim.sh from the fourmee-status skill. Defaults to the
                        copy installed beside this skill. A lane is never
                        started without a claim.
  --dry-run             Print what would happen; create nothing, launch nothing.
  -h, --help            Print this help.

Exit codes:
  0  every selected lane started, or the dry run completed
  1  usage or environment error
  3  no lane could be started
USAGE
}

max_lanes=3
harness="auto"
# Reasoning effort is a second cost axis, independent of the model: the same
# tier can think for longer. Left unset, each harness applies its own default,
# so two lanes on the same tier cost differently for no stated reason. Each task
# carries its own; this is the batch override, empty until asked for, so that a
# task's own effort is not silently replaced by a default nobody chose.
effort_override=""
tasks_dir="delivery/tasks"
# A developer's own choice, so read from the environment: set once, it reaches
# every launch, including the ones follow.sh and the orchestrator start.
worktree_root="${FOURMEE_WORKTREE_ROOT:-}"
log_dir=".lanes/logs"
# The kit installs as a whole, so fourmee-status sits beside this skill. Kept as
# an option because a consuming repository may relocate the scripts; never
# optional in effect, since a lane that cannot claim must not start.
claim_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../fourmee-status/scripts/claim.sh"
publish_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/publish-lane.sh"
implement_skill="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../../fourmee-implement/SKILL.md"
release_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/release-lane.sh"
# Written by the lane inside its worktree, where an unattended session may write,
# and published as the pull request body rather than committed.
lane_report=".lane-report.md"
dry_run=0
web=1
task_ids=()

while (($# > 0)); do
  case "$1" in
    --max-lanes) [[ $# -ge 2 ]] || die "--max-lanes requires a value"; max_lanes="$2"; shift 2 ;;
    --harness) [[ $# -ge 2 ]] || die "--harness requires a value"; harness="$2"; shift 2 ;;
    --effort) [[ $# -ge 2 ]] || die "--effort requires a value"; effort_override="$2"; shift 2 ;;
    --tasks-dir) [[ $# -ge 2 ]] || die "--tasks-dir requires a value"; tasks_dir="$2"; shift 2 ;;
    --worktree-root) [[ $# -ge 2 ]] || die "--worktree-root requires a value"; worktree_root="$2"; shift 2 ;;
    --log-dir) [[ $# -ge 2 ]] || die "--log-dir requires a value"; log_dir="$2"; shift 2 ;;
    --claim-script) [[ $# -ge 2 ]] || die "--claim-script requires a value"; claim_script="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    --no-web) web=0; shift ;;
    -h | --help) usage; exit 0 ;;
    --) shift; while (($# > 0)); do task_ids+=("$1"); shift; done ;;
    -*) die "unknown option: $1" ;;
    *) task_ids+=("$1"); shift ;;
  esac
done

[[ "$max_lanes" =~ ^[1-9][0-9]*$ ]] || die "--max-lanes must be a positive number"
case "$harness" in claude | copilot | auto) ;; *) die "--harness must be claude, copilot, or auto" ;; esac
# The portable set: Claude Code takes low..max, Copilot CLI also takes none and
# minimal. Accepting only the intersection keeps a batch launchable on either
# side, so a value chosen here never fails on one harness and not the other.
valid_effort() {
  case "$1" in
    low | medium | high | xhigh | max) return 0 ;;
    *) return 1 ;;
  esac
}
[[ -z "$effort_override" ]] || valid_effort "$effort_override" ||
  die "--effort must be low, medium, high, xhigh, or max"
[[ -d "$tasks_dir" ]] || die "tasks directory not found: $tasks_dir"
# Without a working claim, concurrent lanes would take the same task and report
# LAUNCHED for every one of them. Refuse to start rather than run unlocked.
[[ -f "$claim_script" ]] || die "claim script not found: $claim_script (pass --claim-script)"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"

# Read ids from stdin when none were passed, so this composes with status.sh.
if ((${#task_ids[@]} == 0)) && [[ ! -t 0 ]]; then
  while read -r line; do
    line="${line%%[[:space:]]*}"
    [[ -n "$line" ]] && task_ids+=("$line")
  done
fi
((${#task_ids[@]} > 0)) || die "no task ids given on the command line or stdin"

field() {
  awk -v key="$2" '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    {
      pos = index($0, ":")
      if (pos == 0) next
      k = substr($0, 1, pos - 1); gsub(/^[ \t]+|[ \t]+$/, "", k)
      if (k != key) next
      v = substr($0, pos + 1); gsub(/^[ \t]+|[ \t]+$/, "", v)
      gsub(/^\[|\]$/, "", v); gsub(/,/, " ", v); gsub(/^[ \t]+|[ \t]+$/, "", v)
      print v; exit
    }
  ' "$1"
}

# A model label names a tier. Routing execution to the most capable model
# everywhere is the single easiest way to exhaust a budget.
harness_for() {
  case "$1" in
    # Mirrors the harness column of the model labels table in the delivery
    # conventions. A test parses that table and fails if the two drift apart.
    opus | sonnet | haiku) printf 'claude' ;;
    terra | luna) printf 'copilot' ;;
    *) printf 'claude' ;;
  esac
}

# opus, sonnet and haiku are Claude models available on both harnesses. terra
# and luna are Copilot-only model names with no Claude Code equivalent, so a
# missing Claude Code has nowhere to send them.
is_portable() {
  case "$1" in
    opus | sonnet | haiku) return 0 ;;
    *) return 1 ;;
  esac
}

# An Anthropic license is not required to use this kit: a developer with only
# a Copilot license has no "claude" binary at all, and every task labelled for
# Claude Code's default would otherwise skip a real launch. Only the real
# launch checks this, not --dry-run: dry-run stays a pure function of the task
# files and flags, unaffected by what happens to be installed on the machine
# previewing it.
fallback_harness() {
  local label="$1" unavailable="$2"
  is_portable "$label" || return 1
  local fallback="copilot"
  [[ "$unavailable" == "copilot" ]] && fallback="claude"
  command -v "$fallback" >/dev/null 2>&1 || return 1
  printf '%s' "$fallback"
}

# The label is the kit's name for a tier; each harness has its own id for it.
# Copilot rejects a bare "sonnet" or "luna" outright ("not available"), so the
# lane would die before doing anything. The ids follow the /models picker in an
# interactive copilot session; `copilot help config` lists stale ones. Probe an
# id with: copilot -p "Reply OK." --model <id>
model_for() {
  local label="$1" side="$2"
  if [[ "$side" == "claude" ]]; then
    case "$label" in
      opus | sonnet | haiku) printf '%s' "$label" ;;
      *) return 1 ;;
    esac
  else
    case "$label" in
      opus) printf 'claude-opus-5.5' ;;
      sonnet) printf 'claude-sonnet-5' ;;
      haiku) printf 'claude-haiku-4.5' ;;
      terra) printf 'gpt-5.6-terra' ;;
      luna) printf 'gpt-6-luna' ;;
      *) return 1 ;;
    esac
  fi
}

# A task with "parallel: false" runs alone: no other lane of the set may be in
# flight while it runs, here or on another developer's machine. Only the remote
# knows what else is in flight, so read it once, and only when some task needs
# it: it costs a fetch and a gh call. A dry run skips the read, as it skips the
# claim, so it reports only what this batch alone decides.
runs_alone() {
  [[ -f "$tasks_dir/$1.md" && "$(field "$tasks_dir/$1.md" parallel)" == false ]]
}
# Every lane starts from the shared default branch as the remote has it now, not
# from this checkout's HEAD: a task launched after its dependency merged must
# build on that merge, and nothing updates a local branch when a pull request
# lands on the forge.
# Read once per repository, on the first lane that lands in it.
declare -A base_of=()
base_for() {
  local dir="$1"
  if [[ -z "${base_of[$dir]:-}" ]]; then
    git -C "$dir" fetch -q origin || return 1
    # A clone sets origin/HEAD; a repository created locally and pushed does not.
    # Asking the remote only writes that one local ref.
    git -C "$dir" symbolic-ref -q refs/remotes/origin/HEAD >/dev/null ||
      git -C "$dir" remote set-head origin --auto >/dev/null 2>&1 || true
    base_of["$dir"]="$(git -C "$dir" symbolic-ref -q --short refs/remotes/origin/HEAD || true)"
    [[ -n "${base_of[$dir]}" ]] || return 1
  fi
  printf '%s' "${base_of[$dir]}"
}

# A task whose change lands in another repository names it with "repo:", the
# directory name of a clone beside this one. The planning files stay here.
home="$(git rev-parse --show-toplevel)"
# Task ids are unique within one use case only. Repositories cloned side by side
# would share a bare ../lanes, and a second use case's a-001 would find the
# first one's worktree in its place.
[[ -n "$worktree_root" ]] || worktree_root="../lanes/$(basename "$home")"
repo_dir_of() {
  local repo
  repo="$(field "$1" repo)"
  if [[ -z "$repo" ]]; then printf '%s' "$home"; else printf '%s' "$(dirname "$home")/$repo"; fi
}
# Paths handed to git -C or to a lane in another repository must not depend on
# the directory they are read from.
absolute() {
  if [[ "$1" == /* ]]; then printf '%s' "$1"; else printf '%s' "$PWD/$1"; fi
}

in_flight=""
alone_in_flight=""
if ((dry_run == 0)) && grep -qsE '^parallel:[[:space:]]*false[[:space:]]*$' "$tasks_dir"/*.md; then
  status_script="$(dirname "$claim_script")/status.sh"
  [[ -f "$status_script" ]] || die "status script not found beside $claim_script"
  rows="$(bash "$status_script" --tasks-dir "$tasks_dir")" ||
    die "task state could not be read, and a task that runs alone needs it"
  while IFS=$'\t' read -r kind id state _; do
    [[ "$kind" == TASK && ("$state" == in-progress || "$state" == in-review) ]] || continue
    in_flight+="${in_flight:+ }$id"
    ! runs_alone "$id" || alone_in_flight="$id"
  done <<<"$rows"
fi

launched=0
alone_started=""
declare -A launched_ids=()

for task_id in "${task_ids[@]}"; do
  ((launched < max_lanes)) || { printf 'SKIP\t%s\tlane cap of %s reached\n' "$task_id" "$max_lanes"; continue; }

  task_file="$tasks_dir/$task_id.md"
  [[ -f "$task_file" ]] || { printf 'SKIP\t%s\tno task file at %s\n' "$task_id" "$task_file"; continue; }

  # Two tasks touching the same files are not parallel, however ready they look.
  # Conflicts are read in both directions, so a one-sided declaration still holds.
  conflict=""
  for other in $(field "$task_file" conflicts_with); do
    [[ -n "${launched_ids[$other]:-}" ]] && { conflict="$other"; break; }
  done
  if [[ -z "$conflict" ]]; then
    for started in "${!launched_ids[@]}"; do
      for other in $(field "$tasks_dir/$started.md" conflicts_with); do
        [[ "$other" == "$task_id" ]] && { conflict="$started"; break 2; }
      done
    done
  fi
  [[ -z "$conflict" ]] || { printf 'SKIP\t%s\tconflicts with running lane %s\n' "$task_id" "$conflict"; continue; }

  [[ -z "$alone_in_flight" ]] ||
    { printf 'SKIP\t%s\t%s runs alone and is in flight\n' "$task_id" "$alone_in_flight"; continue; }
  [[ -z "$alone_started" ]] ||
    { printf 'SKIP\t%s\t%s runs alone\n' "$task_id" "$alone_started"; continue; }
  if runs_alone "$task_id"; then
    [[ -z "$in_flight" ]] ||
      { printf 'SKIP\t%s\truns alone, and tasks are in flight: %s\n' "$task_id" "$in_flight"; continue; }
    ((launched == 0)) ||
      { printf 'SKIP\t%s\truns alone, and this batch already started lanes\n' "$task_id"; continue; }
  fi

  label="$(field "$task_file" model)"
  [[ -n "$label" ]] || label="sonnet"

  # The task states the effort its work needs; --effort overrides the batch, the
  # same way --harness overrides the model label's harness.
  effort="$effort_override"
  if [[ -z "$effort" ]]; then
    effort="$(field "$task_file" effort)"
    [[ -n "$effort" ]] || effort="medium"
  fi
  # The validator rejects an unknown level, so reaching here means the task set
  # was never validated. Skip the lane rather than pass a value one harness will
  # refuse, which would fail after the claim and the worktree already exist.
  valid_effort "$effort" ||
    { printf 'SKIP\t%s\tunknown effort in task file: %s\n' "$task_id" "$effort"; continue; }
  use_harness="$harness"
  [[ "$use_harness" != "auto" ]] || use_harness="$(harness_for "$label")"

  branch="task/$task_id"
  worktree="$worktree_root/$task_id"
  repo_dir="$(repo_dir_of "$task_file")"
  repo_name="$(basename "$repo_dir")"

  if ((dry_run == 1)); then
    model="$(model_for "$label" "$use_harness")" ||
      { printf 'SKIP\t%s\t%s has no %s model\n' "$task_id" "$use_harness" "$label"; continue; }
    printf 'WOULD-LAUNCH\t%s\t%s\t%s\t%s\t%s\t%s\n' "$task_id" "$use_harness" "$model" "$effort" "$worktree" "$repo_name"
    ! runs_alone "$task_id" || alone_started="$task_id"
    launched_ids["$task_id"]=1
    launched=$((launched + 1))
    continue
  fi

  [[ -e "$worktree" ]] && { printf 'SKIP\t%s\tworktree path already exists: %s\n' "$task_id" "$worktree"; continue; }
  if ! command -v "$use_harness" >/dev/null 2>&1; then
    # Only auto-routing falls back. --harness named a side on purpose, and
    # silently moving off it would launch a lane on a harness nobody asked for.
    fallback=""
    if [[ "$harness" == "auto" ]]; then
      fallback="$(fallback_harness "$label" "$use_harness")" || true
    fi
    [[ -n "$fallback" ]] || { printf 'SKIP\t%s\t%s not found on PATH\n' "$task_id" "$use_harness"; continue; }
    use_harness="$fallback"
  fi
  # Resolved after any fallback: the same label has a different id on each side.
  model="$(model_for "$label" "$use_harness")" ||
    { printf 'SKIP\t%s\t%s has no %s model\n' "$task_id" "$use_harness" "$label"; continue; }

  git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
    { printf 'SKIP\t%s\tno clone of %s at %s\n' "$task_id" "$repo_name" "$repo_dir"; continue; }
  # Every lane starts from the shared default branch as the remote has it now,
  # not from a local HEAD: a task launched after its dependency merged must build
  # on that merge, and nothing updates a local branch when a pull request lands.
  base="$(base_for "$repo_dir")" ||
    { printf 'SKIP\t%s\tcannot fetch the default branch of %s; a lane must not start from a stale base\n' "$task_id" "$repo_name"; continue; }
  worktree_abs="$(absolute "$worktree")"
  git -C "$repo_dir" worktree add --quiet -b "$branch" "$worktree_abs" "$base" 2>/dev/null ||
    { printf 'SKIP\t%s\tcould not create worktree on %s\n' "$task_id" "$branch"; continue; }

  # Claim from inside the worktree. Losing the claim is normal, not an error:
  # somebody else got there first, so undo the worktree and move on.
  claim_status=0
  (cd "$worktree_abs" && bash "$claim_script" "$task_id" >/dev/null 2>&1) || claim_status=$?
  if ((claim_status != 0)); then
    # 2 is the claim protocol's "already held". Anything else is a broken claim
    # script or environment, which must not be reported as a lost race.
    if ((claim_status == 2)); then
      printf 'SKIP\t%s\talready claimed by another developer\n' "$task_id"
    else
      printf 'SKIP\t%s\tclaim failed (exit %s)\n' "$task_id" "$claim_status"
    fi
    git -C "$repo_dir" worktree remove --force "$worktree_abs" 2>/dev/null || true
    git -C "$repo_dir" branch -D "$branch" >/dev/null 2>&1 || true
    continue
  fi

  # Resolve the log path before entering the worktree: a relative path would be
  # interpreted from inside the worktree, whose depth depends on --worktree-root.
  mkdir -p "$log_dir"
  log_file="$(cd "$log_dir" && pwd)/$task_id.log"
  # Both harnesses resolve a skill invoked as "/<name> <args>" in -p mode. Claude Code
  # only registers the slash form from .claude/skills, which this repository symlinks
  # to .agents/skills.
  task_path="$tasks_dir/$task_id.md"
  prompt="/fourmee-implement $task_path --report $lane_report"
  # A lane in another repository cannot see this one's planning files from its
  # worktree, so it gets them by absolute path and read access to this checkout.
  # Claude Code loads skills from an added directory; Copilot CLI loads only its
  # .github/skills, so it is pointed at the skill file instead.
  extra=()
  if [[ "$repo_dir" != "$home" ]]; then
    task_path="$(absolute "$task_path")"
    extra=(--add-dir "$home")
    if [[ "$use_harness" == "claude" ]]; then
      prompt="/fourmee-implement $task_path --report $lane_report"
    else
      prompt="Read $implement_skill and follow it as a skill, with the arguments: $task_path --report $lane_report"
    fi
  fi

  if [[ "$use_harness" == "claude" ]]; then
    # acceptEdits alone denies every shell command in -p mode, and nobody is
    # there to approve one, so the lane could not run a single test. Allowing
    # Bash matches Copilot's --allow-all-tools; the denies still win over it.
    allowed=(Bash)
    denied=("Bash(terraform apply:*)" "Bash(terraform destroy:*)")
    # Denied outright rather than left unallowed: a developer's own settings
    # may allow them, and --no-web has to hold regardless.
    if ((web == 1)); then allowed+=(WebFetch WebSearch); else denied+=(WebFetch WebSearch); fi
    session=(claude -p "$prompt"
      "${extra[@]+"${extra[@]}"}"
      --model "$model"
      --effort "$effort"
      --permission-mode acceptEdits
      --allowedTools "${allowed[@]}"
      --disallowedTools "${denied[@]}")
  else
    # --allow-all-tools already covers Copilot's web tools; web_search comes
    # from the built-in GitHub MCP server.
    session=(copilot -p "$prompt"
      "${extra[@]+"${extra[@]}"}"
      --model "$model"
      --reasoning-effort "$effort"
      --allow-all-tools
      --deny-tool 'shell(terraform apply)'
      --deny-tool 'shell(terraform destroy)')
    ((web == 1)) || session+=(--excluded-tools web_fetch web_search)
  fi

  # No stdin: claude -p otherwise waits for piped input before starting.
  # Publish only after a clean exit. A lane that stopped on a bad task reverts
  # its attempt, so the publisher finds nothing and opens no pull request.
  # A failed session releases the claim, unless it left work behind.
  # shellcheck disable=SC2016 # expanded by the inner shell, not this one
  (cd "$worktree_abs" && nohup bash -c \
    'if "${@:5}"; then bash "$1" --report "$3" "$4"; else bash "$2" "$4"; fi' lane \
    "$publish_script" "$release_script" "$lane_report" "$task_path" "${session[@]}" \
    </dev/null >"$log_file" 2>&1 &) || true

  printf 'LAUNCHED\t%s\t%s\t%s\t%s\t%s\t%s\n' "$task_id" "$use_harness" "$model" "$effort" "$worktree" "$repo_name"
  ! runs_alone "$task_id" || alone_started="$task_id"
  launched_ids["$task_id"]=1
  launched=$((launched + 1))
done

printf 'LANES\t%s\n' "$launched"
((launched > 0)) || exit 3
