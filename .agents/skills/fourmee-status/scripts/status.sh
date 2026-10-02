#!/usr/bin/env bash
set -euo pipefail

# Derive the state of every task from git, with no stored status file.
#
#   done         the task's pull request is merged
#   in-review    the task's pull request is open and no longer a draft
#   in-progress  the remote branch task/<id> exists
#   ready        every dependency is done and no branch exists yet
#   blocked      at least one dependency is not done
#
# Nothing here writes state. Two developers running this at the same moment
# see the same answer, because the answer lives in the refs.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: bash status.sh [--tasks-dir <dir>] [--remote <name>] [filter]

Prints one TASK row per task: id, state, holder, title.

Filters (optional, choose one):
  --ready         Only tasks whose dependencies are all done and unclaimed.
  --blocked       Only tasks waiting on an unfinished dependency.
  --in-progress   Only tasks currently claimed.
  --in-review     Only tasks whose pull request is waiting on a reviewer.

Options:
  --tasks-dir <dir>   Directory holding <id>.md task files (default: delivery/tasks).
  --remote <name>     Remote holding the task branches (default: origin).
  --no-fetch          Skip the remote refresh and read cached refs.
  -h, --help          Print this help.
USAGE
}

tasks_dir="delivery/tasks"
remote="origin"
filter=""
do_fetch=1

while (($# > 0)); do
  case "$1" in
    --tasks-dir) [[ $# -ge 2 ]] || die "--tasks-dir requires a value"; tasks_dir="$2"; shift 2 ;;
    --remote) [[ $# -ge 2 ]] || die "--remote requires a value"; remote="$2"; shift 2 ;;
    --ready | --blocked | --in-progress | --in-review) filter="${1#--}"; shift ;;
    --no-fetch) do_fetch=0; shift ;;
    -h | --help) usage; exit 0 ;;
    --) shift; break ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ -d "$tasks_dir" ]] || die "tasks directory not found: $tasks_dir"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"
# Pull request state is the only record that a task is done once its branch is
# deleted on merge. Guessing without it would report merged work as ready, and a
# launcher reading that would implement it again, so refuse instead.
command -v gh >/dev/null 2>&1 || die "gh not found: it is required to tell which tasks are done"

field() {
  awk -v key="$2" '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    {
      pos = index($0, ":")
      if (pos == 0) next
      k = substr($0, 1, pos - 1)
      gsub(/^[ \t]+|[ \t]+$/, "", k)
      if (k != key) next
      v = substr($0, pos + 1)
      gsub(/^[ \t]+|[ \t]+$/, "", v)
      gsub(/^\[|\]$/, "", v); gsub(/,/, " ", v)
      gsub(/^[ \t]+|[ \t]+$/, "", v)
      print v; exit
    }
  ' "$1"
}

shopt -s nullglob
task_files=("$tasks_dir"/*.md)
shopt -u nullglob
((${#task_files[@]} > 0)) || die "no task files found in $tasks_dir"

# A task whose change lands in another repository names it with "repo:": the
# directory name of a clone beside this one. Without it, the task lands here.
home="$(git rev-parse --show-toplevel)"
declare -A depends_of=() title_of=() repo_of=()
ids=()
for file in "${task_files[@]}"; do
  id="$(field "$file" id)"
  [[ -n "$id" ]] || continue
  ids+=("$id")
  depends_of["$id"]="$(field "$file" depends_on)"
  title_of["$id"]="$(field "$file" title)"
  repo="$(field "$file" repo)"
  repo_of["$id"]="$home"
  [[ -z "$repo" ]] || repo_of["$id"]="$(dirname "$home")/$repo"
done

repos=()
while IFS= read -r dir; do
  [[ -n "$dir" ]] || continue
  git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
    die "a task lands in $(basename "$dir"), but $dir is not a clone of it; clone it beside $(basename "$home")"
  repos+=("$dir")
done < <(printf '%s\n' "${repo_of[@]}" | sort -u)

# Pull request heads for one query in one repository. A failed query is fatal: an
# empty answer would read as "nothing merged".
pr_heads() {
  local dir="$1"
  shift
  (cd "$dir" && gh pr list "$@" 2>/dev/null) ||
    die "gh could not list pull requests in $(basename "$dir"); check 'gh auth status' and the remote"
}

# Only a task that lands in the repository answering counts: a task/<id> branch
# or pull request elsewhere is not this task's.
lands_in() {
  [[ -n "${repo_of[$1]:-}" && "${repo_of[$1]}" == "$2" ]]
}

declare -A holder=() done_task=() review_task=()
for dir in "${repos[@]}"; do
  if ((do_fetch == 1)); then
    git -C "$dir" fetch --quiet --prune "$remote" '+refs/heads/task/*:refs/remotes/'"$remote"'/task/*' 2>/dev/null || true
  fi

  # Claimed tasks, and who holds them, straight from the claim commit.
  while IFS=$'\t' read -r ref who; do
    [[ -n "$ref" ]] || continue
    ! lands_in "${ref##*/task/}" "$dir" || holder["${ref##*/task/}"]="$who"
  done < <(git -C "$dir" for-each-ref --format='%(refname)%09%(authorname)' "refs/remotes/$remote/task" 2>/dev/null || true)

  # Merged tasks. Pull request state is the only reliable signal that work
  # landed, because a squash merge leaves the branch commits unreachable.
  merged_heads="$(pr_heads "$dir" --state merged --limit 200 --json headRefName --jq '.[].headRefName')"
  while IFS= read -r head; do
    if [[ "$head" == task/* ]] && lands_in "${head#task/}" "$dir"; then
      done_task["${head#task/}"]=1
    fi
  done <<<"$merged_heads"

  # A lane opens its pull request as a draft and leaves it that way until the
  # work is finished, so "draft" still means the lane is working. Marking it
  # ready for review is the act that hands the task to a human.
  review_heads="$(pr_heads "$dir" --state open --limit 200 --json headRefName,isDraft \
    --jq '.[] | select(.isDraft | not) | .headRefName')"
  while IFS= read -r head; do
    if [[ "$head" == task/* ]] && lands_in "${head#task/}" "$dir"; then
      review_task["${head#task/}"]=1
    fi
  done <<<"$review_heads"
done

# The bulk query above only sees the most recent merged pull requests. Branches
# are usually deleted on merge, so a task merged before that window would have
# neither a branch nor a listed pull request and read as ready, and a launcher
# would implement it again. Ask about each remaining task's own branch instead.
for id in "${ids[@]}"; do
  [[ -z "${done_task[$id]:-}" ]] || continue
  head="$(pr_heads "${repo_of[$id]}" --state merged --head "task/$id" --limit 1 \
    --json headRefName --jq '.[].headRefName')"
  [[ "$head" != "task/$id" ]] || done_task["$id"]=1
done

state_of() {
  local id="$1" dep
  [[ -z "${done_task[$id]:-}" ]] || { printf 'done'; return; }
  # More specific than in-progress: the branch still exists in both, but a pull
  # request out of draft is waiting on a person, not on a lane.
  [[ -z "${review_task[$id]:-}" ]] || { printf 'in-review'; return; }
  [[ -z "${holder[$id]:-}" ]] || { printf 'in-progress'; return; }
  for dep in ${depends_of[$id]:-}; do
    [[ -n "${done_task[$dep]:-}" ]] || { printf 'blocked'; return; }
  done
  printf 'ready'
}

counted_done=0 counted_review=0 counted_prog=0 counted_ready=0 counted_blocked=0
for id in $(printf '%s\n' "${ids[@]}" | sort); do
  state="$(state_of "$id")"
  case "$state" in
    done) counted_done=$((counted_done + 1)) ;;
    in-review) counted_review=$((counted_review + 1)) ;;
    in-progress) counted_prog=$((counted_prog + 1)) ;;
    ready) counted_ready=$((counted_ready + 1)) ;;
    blocked) counted_blocked=$((counted_blocked + 1)) ;;
  esac
  [[ -z "$filter" || "$filter" == "$state" ]] || continue
  printf 'TASK\t%s\t%s\t%s\t%s\n' "$id" "$state" "${holder[$id]:--}" "${title_of[$id]:-}"
done

printf 'SUMMARY\tdone=%s\tin-review=%s\tin-progress=%s\tready=%s\tblocked=%s\n' \
  "$counted_done" "$counted_review" "$counted_prog" "$counted_ready" "$counted_blocked"
