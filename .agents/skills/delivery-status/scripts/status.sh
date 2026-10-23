#!/bin/sh
set -eu

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
usage: sh status.sh [--tasks-dir <dir>] [--remote <name>] [filter]

Prints one TASK row per task: id, state, holder, title. When the
decomposition summary has a Milestones section, also one MILESTONE row per
milestone, in plan order: slug, state, epics, targeted requirement ids.

Milestone states:
  closed        its review note is approved
  undecomposed  the current milestone, with no epics cut yet
  active        the current milestone, with tasks not yet merged
  merged        the current milestone, every task merged, no review note
  reviewing     the current milestone, every task merged, review note in draft
  planned       a milestone after the current one

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

while [ $# -gt 0 ]; do
  case "$1" in
    --tasks-dir) [ $# -ge 2 ] || die "--tasks-dir requires a value"; tasks_dir="$2"; shift 2 ;;
    --remote) [ $# -ge 2 ] || die "--remote requires a value"; remote="$2"; shift 2 ;;
    --ready | --blocked | --in-progress | --in-review) filter="${1#--}"; shift ;;
    --no-fetch) do_fetch=0; shift ;;
    -h | --help) usage; exit 0 ;;
    --) shift; break ;;
    *) die "unknown option: $1" ;;
  esac
done

[ -d "$tasks_dir" ] || die "tasks directory not found: $tasks_dir"
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

# Small maps are directories: one file per key under $store/<map>. POSIX sh has
# no associative arrays, and task ids are slugs, so they are safe file names.
store="$(mktemp -d)"
trap 'rm -rf "$store"' EXIT
tab="$(printf '\t')"

# put <map> <key> <value>, get <map> <key>, has <map> <key>
put() {
  mkdir -p "$store/$1"
  printf '%s' "$3" >"$store/$1/$2"
}
get() { cat "$store/$1/$2" 2>/dev/null || true; }
has() { [ -e "$store/$1/$2" ]; }

# A task whose change lands in another repository names it with "repo:": the
# directory name of a clone beside this one. Without it, the task lands here.
home="$(git rev-parse --show-toplevel)"
ids=""
for file in "$tasks_dir"/*.md; do
  [ -e "$file" ] || continue
  id="$(field "$file" id)"
  [ -n "$id" ] || continue
  ids="$ids$id
"
  put depends_of "$id" "$(field "$file" depends_on)"
  put title_of "$id" "$(field "$file" title)"
  put epic_of "$id" "$(field "$file" epic)"
  repo="$(field "$file" repo)"
  if [ -n "$repo" ]; then put repo_of "$id" "$(dirname "$home")/$repo"; else put repo_of "$id" "$home"; fi
done
[ -n "$ids" ] || die "no task files found in $tasks_dir"

repos="$(for id in $ids; do get repo_of "$id"; printf '\n'; done | sort -u)"
while IFS= read -r dir; do
  [ -n "$dir" ] || continue
  git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
    die "a task lands in $(basename "$dir"), but $dir is not a clone of it; clone it beside $(basename "$home")"
done <<EOF_REPOS
$repos
EOF_REPOS

# Pull request heads for one query in one repository. A failed query is fatal: an
# empty answer would read as "nothing merged".
pr_heads() {
  (cd "$1" && shift && gh pr list "$@" 2>/dev/null) ||
    die "gh could not list pull requests in $(basename "$1"); check 'gh auth status' and the remote"
}

# Only a task that lands in the repository answering counts: a task/<id> branch
# or pull request elsewhere is not this task's.
lands_in() {
  [ "$(get repo_of "$1")" = "$2" ]
}

# record <map> <dir>: read pull request heads on stdin, and mark in <map> each
# task/<id> head whose task lands in <dir>.
record() {
  while IFS= read -r head; do
    case "$head" in
      task/*) if lands_in "${head#task/}" "$2"; then put "$1" "${head#task/}" 1; fi ;;
    esac
  done
}

while IFS= read -r dir; do
  [ -n "$dir" ] || continue
  if [ "$do_fetch" -eq 1 ]; then
    git -C "$dir" fetch --quiet --prune "$remote" '+refs/heads/task/*:refs/remotes/'"$remote"'/task/*' 2>/dev/null || true
  fi

  # Claimed tasks, and who holds them, straight from the claim commit.
  claimed="$(git -C "$dir" for-each-ref --format='%(refname)%09%(authorname)' "refs/remotes/$remote/task" 2>/dev/null || true)"
  while IFS="$tab" read -r ref who; do
    [ -n "$ref" ] || continue
    if lands_in "${ref##*/task/}" "$dir"; then put holder "${ref##*/task/}" "$who"; fi
  done <<EOF_CLAIMED
$claimed
EOF_CLAIMED

  # Merged tasks. Pull request state is the only reliable signal that work
  # landed, because a squash merge leaves the branch commits unreachable.
  merged_heads="$(pr_heads "$dir" --state merged --limit 200 --json headRefName --jq '.[].headRefName')"
  record done_task "$dir" <<EOF_MERGED
$merged_heads
EOF_MERGED

  # A lane opens its pull request as a draft and leaves it that way until the
  # work is finished, so "draft" still means the lane is working. Marking it
  # ready for review is the act that hands the task to a human.
  review_heads="$(pr_heads "$dir" --state open --limit 200 --json headRefName,isDraft \
    --jq '.[] | select(.isDraft | not) | .headRefName')"
  record review_task "$dir" <<EOF_REVIEW
$review_heads
EOF_REVIEW
done <<EOF_REPOS
$repos
EOF_REPOS

# The bulk query above only sees the most recent merged pull requests. Branches
# are usually deleted on merge, so a task merged before that window would have
# neither a branch nor a listed pull request and read as ready, and a launcher
# would implement it again. Ask about each remaining task's own branch instead.
for id in $ids; do
  ! has done_task "$id" || continue
  head="$(pr_heads "$(get repo_of "$id")" --state merged --head "task/$id" --limit 1 \
    --json headRefName --jq '.[].headRefName')"
  [ "$head" != "task/$id" ] || put done_task "$id" 1
done

state_of() (
  id="$1"
  has done_task "$id" && { printf 'done'; return; }
  # More specific than in-progress: the branch still exists in both, but a pull
  # request out of draft is waiting on a person, not on a lane.
  has review_task "$id" && { printf 'in-review'; return; }
  has holder "$id" && { printf 'in-progress'; return; }
  for dep in $(get depends_of "$id"); do
    has done_task "$dep" || { printf 'blocked'; return; }
  done
  printf 'ready'
)

counted_done=0 counted_review=0 counted_prog=0 counted_ready=0 counted_blocked=0
for id in $(printf '%s' "$ids" | sort); do
  state="$(state_of "$id")"
  case "$state" in
    done) counted_done=$((counted_done + 1)) ;;
    in-review) counted_review=$((counted_review + 1)) ;;
    in-progress) counted_prog=$((counted_prog + 1)) ;;
    ready) counted_ready=$((counted_ready + 1)) ;;
    blocked) counted_blocked=$((counted_blocked + 1)) ;;
  esac
  [ -z "$filter" ] || [ "$filter" = "$state" ] || continue
  who="$(get holder "$id")"
  printf 'TASK\t%s\t%s\t%s\t%s\n' "$id" "$state" "${who:--}" "$(get title_of "$id")"
done

# Milestones, when the plan has them. The current milestone is the first one
# whose review note is not approved: only it has tasks still to merge, so its
# state is read from theirs. The parsing mirrors the Milestones section of the
# decomposition template: a "### <slug>" heading per milestone, then
# "**Epics:**" and "**Requirements:**" lines, either of which may wrap.
plan_dir="$(dirname "$tasks_dir")"
milestones="$(awk '
  # An empty list is written "-": read splits on tabs as whitespace, and would
  # otherwise shift the fields after it.
  function flush() { if (slug != "") printf "%s\t%s\t%s\n", slug, (epics == "" ? "-" : epics), (targets == "" ? "-" : targets) }
  function ids(s) {
    sub(/^\*\*[A-Za-z]+:\*\*/, "", s); gsub(/\([^)]*\)/, " ", s); gsub(/,/, " ", s)
    gsub(/[ \t]+/, " ", s); sub(/^ /, "", s); sub(/ $/, "", s); return s
  }
  /^##[[:space:]]/ { flush(); slug = ""; in_plan = ($0 ~ /^##[[:space:]]+Milestones[[:space:]]*$/); next }
  !in_plan { next }
  /^###[[:space:]]/ {
    flush(); slug = $0; sub(/^###[[:space:]]+/, "", slug); sub(/[[:space:]]+$/, "", slug)
    epics = ""; targets = ""; open = ""; next
  }
  slug == "" { next }
  /^\*\*Epics:\*\*/ { epics = ids($0); open = "epics"; next }
  /^\*\*Requirements:\*\*/ { targets = ids($0); open = "targets"; next }
  /^[ \t]*$/ || /^\*\*/ { open = ""; next }
  open == "epics" { epics = ids(epics " " $0) }
  open == "targets" { targets = ids(targets " " $0) }
  END { flush() }
' "$plan_dir/decomposition.md" 2>/dev/null || true)"

# reviewed <slug>: the review note's status, empty when there is no note.
reviewed() {
  [ -f "$plan_dir/milestones/$1.md" ] || return 0
  awk '/^\*\*Status:\*\*/ { sub(/^\*\*Status:\*\*[ \t]*/, ""); sub(/[ \t]+$/, ""); print tolower($0); exit }' \
    "$plan_dir/milestones/$1.md"
}

if [ -z "$filter" ] && [ -n "$milestones" ]; then
  current=""
  while IFS="$tab" read -r slug epics targets; do
    [ "$epics" != - ] || epics=""
    [ "$targets" != - ] || targets=""
    review="$(reviewed "$slug")"
    if [ "$review" = approved ]; then
      state=closed
    elif [ -n "$current" ]; then
      state=planned
    else
      current="$slug"
      if [ -z "$epics" ]; then
        state=undecomposed
      else
        state=merged
        for id in $ids; do
          case " $epics " in *" $(get epic_of "$id") "*) ;; *) continue ;; esac
          [ "$(state_of "$id")" = "done" ] || state=active
        done
        [ "$state" != merged ] || [ -z "$review" ] || state=reviewing
      fi
    fi
    printf 'MILESTONE\t%s\t%s\t%s\t%s\n' "$slug" "$state" "${epics:--}" "${targets:--}"
  done <<EOF_MILESTONES
$milestones
EOF_MILESTONES
fi

printf 'SUMMARY\tdone=%s\tin-review=%s\tin-progress=%s\tready=%s\tblocked=%s\n' \
  "$counted_done" "$counted_review" "$counted_prog" "$counted_ready" "$counted_blocked"
