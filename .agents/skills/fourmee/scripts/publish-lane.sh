#!/bin/sh
set -eu

# Turn a finished lane into a draft pull request: commit, push, open.
#
# The launcher runs this in the lane worktree once the session exits cleanly.
# fourmee-implement leaves its change uncommitted on purpose, so it stays free
# of git lifecycle; nothing here needs judgement, so it belongs in a script rather
# than in the lane's prompt.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: sh publish-lane.sh [options] <task-file>

Run from the root of the lane worktree, on branch task/<id>. Commits every
change except the report, pushes the branch, and opens a draft pull request.

Options:
  --report <path>   Handoff report the lane wrote, relative to the worktree
                    (default: .lane-report.md). Never committed. It is the
                    whole pull request body when the repository has a pull
                    request template, which the lane fills; otherwise it
                    follows the task's acceptance criteria.
  --remote <name>   Shared remote (default: origin).
  -h, --help        Print this help.

Prints one line, tab-separated:
  PUBLISHED  <id>  <pull request url>
  NOTHING    <id>  <reason>

Exit codes:
  0  published, or the pull request already existed and was updated
  1  usage or environment error, including a failed commit, push or gh call
  3  nothing to publish: the lane left no change
USAGE
}

report=".lane-report.md"
remote="origin"
task_file=""

while [ $# -gt 0 ]; do
  case "$1" in
    --report) [ $# -ge 2 ] || die "--report requires a value"; report="$2"; shift 2 ;;
    --remote) [ $# -ge 2 ] || die "--remote requires a value"; remote="$2"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) [ -z "$task_file" ] || die "one task file only"; task_file="$1"; shift ;;
  esac
done

[ -n "$task_file" ] || die "no task file given"
[ -f "$task_file" ] || die "task file not found: $task_file"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"
[ "$(git rev-parse --show-toplevel)" = "$(pwd -P)" ] || die "run from the root of the lane worktree"

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
      print v; exit
    }
  ' "$1"
}

task_id="$(basename "$task_file" .md)"
branch="task/$task_id"
[ "$(git symbolic-ref --short -q HEAD)" = "$branch" ] || die "not on $branch"

title="$(field "$task_file" title)"
epic="$(field "$task_file" epic)"
type="$(field "$task_file" type)"
[ -n "$title" ] || die "task file has no title"
[ -n "$type" ] || type="feat"
# Task titles are sentence case; commit subjects are not. Leave an acronym alone.
case "$title" in
  [[:upper:]][[:lower:]]*) title="$(printf '%s' "$title" | cut -c1 | tr '[:upper:]' '[:lower:]')${title#?}" ;;
esac
subject="$type${epic:+($epic)}: $title"

# A task planned in another repository is named by a link to it there: its path
# on this machine means nothing to a reviewer. "blob/HEAD" is the default branch.
# shellcheck disable=SC2016 # the backticks are Markdown, not command substitution
task_md='`'"$task_file"'`'
task_ref="$task_file"
task_dir="$(cd "$(dirname "$task_file")" && pwd -P)"
outside=0
case "$task_dir/" in "$(pwd -P)/"*) ;; *) outside=1 ;; esac
if [ "$outside" -eq 1 ] && home="$(git -C "$task_dir" rev-parse --show-toplevel 2>/dev/null)"; then
  rel="$task_dir/$(basename "$task_file")"
  rel="${rel#"$home"/}"
  task_ref="$(basename "$home")/$rel"
  task_md='`'"$task_ref"'`'
  if home_url="$(git -C "$home" remote get-url "$remote" 2>/dev/null)"; then
    home_url="${home_url%.git}"
    case "$home_url" in
      git@*:*) home_url="${home_url#git@}"; home_url="https://${home_url%%:*}/${home_url#*:}" ;;
    esac
    case "$home_url" in
      https://*)
        task_ref="$home_url/blob/HEAD/$rel"
        task_md="[$rel]($task_ref)"
        ;;
    esac
  fi
fi

# The worktree holds nothing but this lane's work, so every change is the
# task's, except the report, which belongs in the pull request and not the diff.
git add -A -- . ":(exclude)$report"
if ! git diff --cached --quiet; then
  git commit -q -m "$subject" -m "Task: $task_ref" || die "commit failed; the change is still staged in $(pwd)"
fi

# The lane's work is whatever sits on top of its claim commit. Comparing with the
# remote branch instead would read an already pushed lane as empty, and a re-run
# could then never open a pull request that is missing.
case "$(git log -1 --format=%s HEAD)" in
  "chore(claim): task $task_id "*)
    printf 'NOTHING\t%s\tthe lane left no change\n' "$task_id"
    exit 3
    ;;
esac

git push -q "$remote" "HEAD:refs/heads/$branch" || die "push of $branch failed"

command -v gh >/dev/null 2>&1 || die "gh not found; $branch is pushed, open the pull request by hand"

# The open pull request for the branch, if any. A closed one does not count: a
# task released and relaunched after its pull request was closed needs a new one.
open_pr() (
  view="$(gh pr view "$branch" --json state,url --jq '.state + " " + .url' 2>/dev/null)" || return 1
  [ "${view%% *}" = OPEN ] && [ -n "${view#* }" ] && printf '%s' "${view#* }"
)

# A re-run after a fix only needs the push: the pull request tracks the branch.
if url="$(open_pr)"; then
  printf 'PUBLISHED\t%s\t%s\n' "$task_id" "$url"
  exit 0
fi

# GitHub's locations for a pull request template, in any case, single or several.
has_template() (
  for dir in . .github docs; do
    [ -d "$dir" ] || continue
    entries="$(ls -1 "$dir")"
    if printf '%s\n' "$entries" | grep -qi '^pull_request_template\.md$'; then return 0; fi
    sub="$(printf '%s\n' "$entries" | grep -i '^pull_request_template$' | head -n 1)"
    [ -n "$sub" ] || continue
    for template in "$dir/$sub"/*.[mM][dD]; do
      [ -e "$template" ] && return 0
    done
  done
  return 1
)

body="$(mktemp)"
trap 'rm -f "$body"' EXIT
if [ -s "$report" ] && has_template; then
  # The lane wrote its report in the template's shape; it is the whole body.
  cp "$report" "$body"
else
  # shellcheck disable=SC2016 # the backticks are Markdown, not command substitution
  {
    printf 'Task: %s\n\n' "$task_md"
    # Reviewers check the diff against these, so they are repeated rather than linked.
    awk '
      tolower($0) ~ /^#+[ \t]*acceptance criteria/ { on = 1; print "## Acceptance criteria"; next }
      on && /^#+ / { exit }
      on { print }
    ' "$task_file"
    printf '\n## Lane report\n\n'
    if [ -s "$report" ]; then
      cat "$report"
    else
      printf 'The lane wrote no report. Its session log is `.lanes/logs/%s.log` on the machine that launched it.\n' "$task_id"
    fi
  } >"$body"
fi

create_pr() {
  gh pr create --draft --head "$branch" --title "$subject" --body-file "$body" "$@"
}
if ! url="$(create_pr --label ai-assisted 2>/dev/null)"; then
  # Usually a repository without the label. The pull request matters more than
  # the label, but the failed call may still have opened it, so look first
  # rather than open a second one.
  printf 'WARN\t%s\tthe ai-assisted label could not be applied\n' "$task_id" >&2
  url="$(open_pr)" ||
    url="$(create_pr)" ||
    die "gh pr create failed; $branch is pushed, open the pull request by hand"
fi

printf 'PUBLISHED\t%s\t%s\n' "$task_id" "$(printf '%s\n' "$url" | tail -n 1)"
