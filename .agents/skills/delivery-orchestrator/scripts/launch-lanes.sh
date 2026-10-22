#!/bin/sh
set -eu

# Start one lane per task: a git worktree, a claim, and a headless agent session
# that ends in a draft pull request.
#
# Task ids come from the arguments, or from stdin when none are given, so this
# composes with whatever decided the tasks were ready:
#
#   sh status.sh --ready | awk '$1=="TASK" {print $2}' | sh launch-lanes.sh
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
usage: sh launch-lanes.sh [options] [task-id...]

Starts a lane per task id, reading ids from stdin when none are given. A task
with a repo field gets its worktree, claim and pull request in that clone,
beside this repository; the lane reads its task file and contracts here. A lane
whose session exits cleanly is published as a draft pull request by
publish-lane.sh; one whose session fails without leaving work behind gives its
claim back through release-lane.sh. Both sit beside this script.

Options:
  --max-lanes <n>       Most lanes to run at once (default: 3).
  --harness <name>      claude, copilot, codex, opencode, pi, custom, or auto
                        (default: auto). auto uses the harness the task's tier
                        maps to in tiers.conf, then $DELIVERY_HARNESS, then the
                        first one installed. Naming one forces every lane in the
                        batch onto it. custom runs $DELIVERY_LANE_CMD, a command
                        line with {prompt}, {model}, {worktree} and {plan_dir}
                        in it, for a harness this launcher does not know.
  --tasks-dir <dir>     Directory holding <id>.md task files (default: delivery/tasks).
  --worktree-root <dir> Directory that receives one <task-id> worktree per lane.
                        Defaults to $DELIVERY_WORKTREE_ROOT when set, else to
                        ../lanes/<name of this repository>.
  --log-dir <dir>       Where session logs are written (default: .lanes/logs).
  --no-web              Take web fetch and web search away from the lanes.
                        SECURITY: web access is on by default, and it is a
                        prompt-injection path. A lane runs unattended with a
                        shell and your git credentials, and a fetched page is
                        text the model may follow. Use --no-web when lanes
                        should build from the repository and its contracts
                        alone. The shell can still reach the network.
  --claim-script <path> claim.sh from the delivery-status skill. Defaults to the
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
harness_flag=""
env_harness="${DELIVERY_HARNESS:-}"
tasks_dir="delivery/tasks"
# A developer's own choice, so read from the environment: set once, it reaches
# every launch, including the ones follow.sh and the orchestrator start.
worktree_root="${DELIVERY_WORKTREE_ROOT:-}"
log_dir=".lanes/logs"
# The kit installs as a whole, so delivery-status sits beside this skill. Kept as
# an option because a consuming repository may relocate the scripts; never
# optional in effect, since a lane that cannot claim must not start.
here="$(cd "$(dirname "$0")" && pwd)"
claim_script="$here/../../delivery-status/scripts/claim.sh"
publish_script="$here/publish-lane.sh"
release_script="$here/release-lane.sh"
implement_skill="$here/../../delivery-implement/SKILL.md"
harness_lib="$here/harness.sh"
# Written by the lane inside its worktree, where an unattended session may write,
# and published as the pull request body rather than committed.
lane_report=".lane-report.md"
dry_run=0
web=1
task_ids=""

[ -f "$harness_lib" ] || die "harness adapters not found: $harness_lib"
# A lane is told to follow this file. Without it the session would run with no
# skill at all, so a split install stops here rather than in every lane.
[ -f "$implement_skill" ] ||
  die "delivery-implement is not installed beside delivery-orchestrator in $(cd -P "$here/../.." && pwd -P): reinstall the kit whole"
# shellcheck source=harness.sh source-path=SCRIPTDIR
. "$harness_lib"

while [ $# -gt 0 ]; do
  case "$1" in
    --max-lanes) [ $# -ge 2 ] || die "--max-lanes requires a value"; max_lanes="$2"; shift 2 ;;
    --harness) [ $# -ge 2 ] || die "--harness requires a value"; harness_flag="$2"; shift 2 ;;
    --tasks-dir) [ $# -ge 2 ] || die "--tasks-dir requires a value"; tasks_dir="$2"; shift 2 ;;
    --worktree-root) [ $# -ge 2 ] || die "--worktree-root requires a value"; worktree_root="$2"; shift 2 ;;
    --log-dir) [ $# -ge 2 ] || die "--log-dir requires a value"; log_dir="$2"; shift 2 ;;
    --claim-script) [ $# -ge 2 ] || die "--claim-script requires a value"; claim_script="$2"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    --no-web) web=0; shift ;;
    -h | --help) usage; exit 0 ;;
    --) shift; while [ $# -gt 0 ]; do task_ids="$task_ids$1
"; shift; done ;;
    -*) die "unknown option: $1" ;;
    *) task_ids="$task_ids$1
"; shift ;;
  esac
done

case "$max_lanes" in "" | 0* | *[!0-9]*) die "--max-lanes must be a positive number" ;; esac
# auto is the same as not choosing, so it is stored as nothing.
[ "$harness_flag" != auto ] || harness_flag=""
[ "$env_harness" != auto ] || env_harness=""
[ -z "$harness_flag" ] || is_harness "$harness_flag" || die "--harness must be one of: $HARNESSES custom auto"
[ -z "$env_harness" ] || is_harness "$env_harness" || die "DELIVERY_HARNESS must be one of: $HARNESSES custom auto"
[ -d "$tasks_dir" ] || die "tasks directory not found: $tasks_dir"
# Without a working claim, concurrent lanes would take the same task and report
# LAUNCHED for every one of them. Refuse to start rather than run unlocked.
[ -f "$claim_script" ] || die "claim script not found: $claim_script (pass --claim-script)"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"

# Read ids from stdin when none were passed, so this composes with status.sh.
if [ -z "$task_ids" ] && [ ! -t 0 ]; then
  while read -r line; do
    line="${line%%[[:space:]]*}"
    [ -z "$line" ] || task_ids="$task_ids$line
"
  done
fi
[ -n "$task_ids" ] || die "no task ids given on the command line or stdin"

# What the launcher remembers lives in files, since POSIX sh has no arrays or
# associative arrays. A map is a directory with one file per key, a list is a
# file with one entry per line. Keys are task ids and tiers, which are slugs.
store="$(mktemp -d)"
trap 'rm -rf "$store"' EXIT
tab="$(printf '\t')"

put() { mkdir -p "$store/$1"; printf '%s' "$3" >"$store/$1/$2"; }
get() { cat "$store/$1/$2" 2>/dev/null || true; }
has() { [ -e "$store/$1/$2" ]; }

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

# A tier is a hint about how much capability a task needs; which model that
# means is the developer's choice, read from tiers.conf. Two files are read and
# the first to name a tier wins: the developer's own, outside every repository,
# then the project's. A tier no file names passes no model flag, and the harness
# applies its own default.
is_tier() {
  case "$1" in plan | build | chore) return 0 ;; *) return 1 ;; esac
}

# A mapping is a git config file, one section per tier, read with git itself:
#
#   [chore]
#       harness = copilot
#       model = gpt-6-luna
#
# git is already required, so nothing here parses text. It brings the comments,
# the quoting and the syntax errors, which it reports with the file and line.
# What git cannot know is checked below: a section must be a tier and a key one
# of harness, model and advisor. The result is the tier_harness, tier_model and
# tier_advisor maps, where an empty value means a tier the file names without
# that key.
load_tiers() {
  user_conf="${XDG_CONFIG_HOME:-${HOME:-}/.config}/delivery-kit/tiers.conf"
  files=""
  if [ -n "${DELIVERY_TIERS:-}" ]; then
    [ -f "$DELIVERY_TIERS" ] || die "DELIVERY_TIERS names a missing file: $DELIVERY_TIERS"
    files="$DELIVERY_TIERS
"
  elif [ -f "$user_conf" ]; then
    files="$user_conf
"
  fi
  [ ! -f "$(dirname "$tasks_dir")/tiers.conf" ] || files="$files$(dirname "$tasks_dir")/tiers.conf
"
  [ -n "$files" ] || return 0
  while IFS= read -r file <&3; do
    [ -n "$file" ] || continue
    rm -rf "$store/named" "$store/file_harness" "$store/file_model" "$store/file_advisor"
    : >"$store/seen"
    out="$(git config --file "$file" --list 2>&1)" || die "${out#fatal: }"
    while IFS= read -r line; do
      [ -n "$line" ] || continue
      case "$line" in *=*) ;; *) die "$file: '$line' has no value" ;; esac
      name="${line%%=*}"
      value="${line#*=}"
      case "$name" in *.*) ;; *) die "$file: unexpected key '$name' (expected a [tier] section)" ;; esac
      tier="${name%%.*}"
      key="${name#*.}"
      case "$key" in *.*) die "$file: unexpected key '$name' (expected a [tier] section)" ;; esac
      is_tier "$tier" || die "$file: unknown tier '$tier' (expected plan, build, or chore)"
      case "$key" in harness | model | advisor) ;; *) die "$file: unknown key '$name' (expected harness, model, or advisor)" ;; esac
      ! grep -Fxq -- "$name" "$store/seen" || die "$file: $name is set twice"
      printf '%s\n' "$name" >>"$store/seen"
      put named "$tier" 1
      if [ "$key" = harness ]; then
        [ -z "$value" ] || is_harness "$value" ||
          die "$file: unknown harness '$value' (expected one of: $HARNESSES custom)"
      fi
      put "file_$key" "$tier" "$value"
    done <<EOF_CONF
$out
EOF_CONF
    # The first file to name a tier decides all of it, every key alike.
    for tier in plan build chore; do
      has named "$tier" || continue
      has tier_decided "$tier" && continue
      put tier_decided "$tier" 1
      put tier_harness "$tier" "$(get file_harness "$tier")"
      put tier_model "$tier" "$(get file_model "$tier")"
      put tier_advisor "$tier" "$(get file_advisor "$tier")"
    done
  done 3<<EOF_FILES
$files
EOF_FILES
}

# The model or advisor a tier maps to, when it applies to the harness the lane
# runs on. A mapping names its harness because a model id means nothing to
# another one: passing it through would end the session at startup.
#   mapped_for <tier_model|tier_advisor> <tier> <harness>
mapped_for() {
  mapped="$(get "$1" "$2")"
  mapped_harness="$(get tier_harness "$2")"
  [ -n "$mapped" ] || return 0
  [ -z "$mapped_harness" ] || [ "$mapped_harness" = "$3" ] || return 0
  printf '%s' "$mapped"
}
load_tiers

# A task with "parallel: false" runs alone: no other lane of the set may be in
# flight while it runs, here or on another developer's machine. Only the remote
# knows what else is in flight, so read it once, and only when some task needs
# it: it costs a fetch and a gh call. A dry run skips the read, as it skips the
# claim, so it reports only what this batch alone decides.
runs_alone() {
  [ -f "$tasks_dir/$1.md" ] && [ "$(field "$tasks_dir/$1.md" parallel)" = false ]
}

# Every lane starts from the shared default branch as the remote has it now, not
# from this checkout's HEAD: a task launched after its dependency merged must
# build on that merge, and nothing updates a local branch when a pull request
# lands on the forge. Read once per repository, on the first lane that lands in
# it; the cache is a file of "<dir><TAB><base>" lines.
cached_base() {
  DIR="$1" awk -F'\t' '$1 == ENVIRON["DIR"] { print $2; exit }' "$store/bases" 2>/dev/null || true
}
base_for() {
  base="$(cached_base "$1")"
  if [ -z "$base" ]; then
    git -C "$1" fetch -q origin || return 1
    # A clone sets origin/HEAD; a repository created locally and pushed does not.
    # Asking the remote only writes that one local ref.
    git -C "$1" symbolic-ref -q refs/remotes/origin/HEAD >/dev/null ||
      git -C "$1" remote set-head origin --auto >/dev/null 2>&1 || true
    base="$(git -C "$1" symbolic-ref -q --short refs/remotes/origin/HEAD || true)"
    [ -n "$base" ] || return 1
    printf '%s\t%s\n' "$1" "$base" >>"$store/bases"
  fi
  printf '%s' "$base"
}

# A task whose change lands in another repository names it with "repo:", the
# directory name of a clone beside this one. The planning files stay here.
home="$(git rev-parse --show-toplevel)"
# Task ids are unique within one project only. Repositories cloned side by side
# would share a bare ../lanes, and a second project's a-001 would find the
# first one's worktree in its place.
[ -n "$worktree_root" ] || worktree_root="../lanes/$(basename "$home")"
repo_dir_of() {
  repo="$(field "$1" repo)"
  if [ -z "$repo" ]; then printf '%s' "$home"; else printf '%s' "$(dirname "$home")/$repo"; fi
}
# Paths handed to git -C or to a lane in another repository must not depend on
# the directory they are read from.
absolute() {
  case "$1" in /*) printf '%s' "$1" ;; *) printf '%s' "$PWD/$1" ;; esac
}

in_flight=""
alone_in_flight=""
if [ "$dry_run" -eq 0 ] && grep -qsE '^parallel:[[:space:]]*false[[:space:]]*$' "$tasks_dir"/*.md; then
  status_script="$(dirname "$claim_script")/status.sh"
  [ -f "$status_script" ] || die "status script not found beside $claim_script"
  rows="$(sh "$status_script" --tasks-dir "$tasks_dir")" ||
    die "task state could not be read, and a task that runs alone needs it"
  while IFS="$tab" read -r kind id state _; do
    [ "$kind" = TASK ] || continue
    case "$state" in in-progress | in-review) ;; *) continue ;; esac
    in_flight="$in_flight${in_flight:+ }$id"
    ! runs_alone "$id" || alone_in_flight="$id"
  done <<EOF_ROWS
$rows
EOF_ROWS
fi

launched=0
alone_started=""
: >"$store/launched_ids"

# Ids are read from file descriptor 3, so that nothing the loop runs can take
# them from its standard input.
while IFS= read -r task_id <&3; do
  [ -n "$task_id" ] || continue
  [ "$launched" -lt "$max_lanes" ] || { printf 'SKIP\t%s\tlane cap of %s reached\n' "$task_id" "$max_lanes"; continue; }

  task_file="$tasks_dir/$task_id.md"
  [ -f "$task_file" ] || { printf 'SKIP\t%s\tno task file at %s\n' "$task_id" "$task_file"; continue; }

  # Two tasks touching the same files are not parallel, however ready they look.
  # Conflicts are read in both directions, so a one-sided declaration still holds.
  conflict=""
  for other in $(field "$task_file" conflicts_with); do
    if grep -Fxq -- "$other" "$store/launched_ids"; then conflict="$other"; break; fi
  done
  if [ -z "$conflict" ]; then
    while IFS= read -r started; do
      for other in $(field "$tasks_dir/$started.md" conflicts_with); do
        if [ "$other" = "$task_id" ]; then conflict="$started"; break; fi
      done
      [ -z "$conflict" ] || break
    done <"$store/launched_ids"
  fi
  [ -z "$conflict" ] || { printf 'SKIP\t%s\tconflicts with running lane %s\n' "$task_id" "$conflict"; continue; }

  [ -z "$alone_in_flight" ] ||
    { printf 'SKIP\t%s\t%s runs alone and is in flight\n' "$task_id" "$alone_in_flight"; continue; }
  [ -z "$alone_started" ] ||
    { printf 'SKIP\t%s\t%s runs alone\n' "$task_id" "$alone_started"; continue; }
  if runs_alone "$task_id"; then
    [ -z "$in_flight" ] ||
      { printf 'SKIP\t%s\truns alone, and tasks are in flight: %s\n' "$task_id" "$in_flight"; continue; }
    [ "$launched" -eq 0 ] ||
      { printf 'SKIP\t%s\truns alone, and this batch already started lanes\n' "$task_id"; continue; }
  fi

  tier="$(field "$task_file" tier)"
  [ -n "$tier" ] || tier="build"
  # The validator rejects an unknown tier, so reaching here means the task set
  # was never validated.
  is_tier "$tier" ||
    { printf 'SKIP\t%s\tunknown tier in task file: %s (expected plan, build, or chore)\n' "$task_id" "$tier"; continue; }

  # --harness is the operator's choice for the batch and wins; then the tier's
  # own mapping, then the developer's default. What is left is auto, decided at
  # launch from what is installed.
  use_harness="auto"
  tier_harness="$(get tier_harness "$tier")"
  if [ -n "$harness_flag" ]; then
    use_harness="$harness_flag"
  elif [ -n "$tier_harness" ]; then
    use_harness="$tier_harness"
  elif [ -n "$env_harness" ]; then
    use_harness="$env_harness"
  fi

  branch="task/$task_id"
  worktree="$worktree_root/$task_id"
  repo_dir="$(repo_dir_of "$task_file")"
  repo_name="$(basename "$repo_dir")"

  if [ "$dry_run" -eq 1 ]; then
    model="$(mapped_for tier_model "$tier" "$use_harness")"
    printf 'WOULD-LAUNCH\t%s\t%s\t%s\t%s\t%s\n' "$task_id" "$use_harness" "${model:-default}" "$worktree" "$repo_name"
    ! runs_alone "$task_id" || alone_started="$task_id"
    printf '%s\n' "$task_id" >>"$store/launched_ids"
    launched=$((launched + 1))
    continue
  fi

  [ ! -e "$worktree" ] || { printf 'SKIP\t%s\tworktree path already exists: %s\n' "$task_id" "$worktree"; continue; }
  if [ "$use_harness" = "auto" ]; then
    # Nothing chose a harness, so use the first one this machine has.
    for candidate in $HARNESSES; do
      if command -v "$candidate" >/dev/null 2>&1; then use_harness="$candidate"; break; fi
    done
    [ "$use_harness" != "auto" ] ||
      { printf 'SKIP\t%s\tno supported harness on PATH (%s)\n' "$task_id" "$HARNESSES"; continue; }
  elif [ "$use_harness" = custom ]; then
    [ -n "${DELIVERY_LANE_CMD:-}" ] ||
      { printf 'SKIP\t%s\tcustom needs DELIVERY_LANE_CMD to be set\n' "$task_id"; continue; }
  elif ! command -v "$use_harness" >/dev/null 2>&1; then
    # A harness somebody chose is never swapped for another: a lane on a harness
    # nobody asked for would spend an allowance nobody meant to spend.
    printf 'SKIP\t%s\t%s not found on PATH\n' "$task_id" "$use_harness"
    continue
  fi
  # Resolved after the harness is known: a mapping names the one it is for.
  model="$(mapped_for tier_model "$tier" "$use_harness")"
  advisor="$(mapped_for tier_advisor "$tier" "$use_harness")"

  git -C "$repo_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
    { printf 'SKIP\t%s\tno clone of %s at %s\n' "$task_id" "$repo_name" "$repo_dir"; continue; }
  base="$(base_for "$repo_dir")" ||
    { printf 'SKIP\t%s\tcannot fetch the default branch of %s; a lane must not start from a stale base\n' "$task_id" "$repo_name"; continue; }
  worktree_abs="$(absolute "$worktree")"
  git -C "$repo_dir" worktree add --quiet -b "$branch" "$worktree_abs" "$base" 2>/dev/null ||
    { printf 'SKIP\t%s\tcould not create worktree on %s\n' "$task_id" "$branch"; continue; }

  # Claim from inside the worktree. Losing the claim is normal, not an error:
  # somebody else got there first, so undo the worktree and move on.
  claim_status=0
  (cd "$worktree_abs" && sh "$claim_script" "$task_id" >/dev/null 2>&1) || claim_status=$?
  if [ "$claim_status" -ne 0 ]; then
    # 2 is the claim protocol's "already held". Anything else is a broken claim
    # script or environment, which must not be reported as a lost race.
    if [ "$claim_status" -eq 2 ]; then
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

  # A lane in another repository cannot see this one's planning files from its
  # worktree, so it gets them by absolute path and access to this checkout.
  task_path="$tasks_dir/$task_id.md"
  add_dir=""
  cross_repo=0
  if [ "$repo_dir" != "$home" ]; then
    task_path="$(absolute "$task_path")"
    add_dir="$home"
    cross_repo=1
  fi
  prompt="$(harness_prompt "$use_harness" "$cross_repo" "$implement_skill" "$task_path --report $lane_report")"

  # No stdin: claude -p otherwise waits for piped input before starting.
  # Publish only after a clean exit. A lane that stopped on a bad task reverts
  # its attempt, so the publisher finds nothing and opens no pull request.
  # A failed session releases the claim, unless it left work behind.
  # shellcheck disable=SC2016 # expanded by the inner shell, not this one
  (cd "$worktree_abs" && nohup sh -c '
    lib="$1" publish="$2" release="$3" report="$4" task="$5"
    shift 5
    . "$lib"
    if harness_run "$@"; then sh "$publish" --report "$report" "$task"; else sh "$release" "$task"; fi
  ' lane "$harness_lib" "$publish_script" "$release_script" "$lane_report" "$task_path" \
    "$use_harness" "$prompt" "$model" "$advisor" "$add_dir" "$home" "$web" \
    </dev/null >"$log_file" 2>&1 &) || true

  printf 'LAUNCHED\t%s\t%s\t%s\t%s\t%s\n' "$task_id" "$use_harness" "${model:-default}" "$worktree" "$repo_name"
  ! runs_alone "$task_id" || alone_started="$task_id"
  printf '%s\n' "$task_id" >>"$store/launched_ids"
  launched=$((launched + 1))
done 3<<EOF_IDS
$task_ids
EOF_IDS

printf 'LANES\t%s\n' "$launched"
[ "$launched" -gt 0 ] || exit 3
