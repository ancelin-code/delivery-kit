#!/usr/bin/env bash
set -euo pipefail

# Fail early and clearly on an older bash, such as the 3.2 macOS ships.
if ((BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4))); then
  printf 'ERROR\tbash 4.4 or later is required, found %s\n' "$BASH_VERSION" >&2
  exit 1
fi

# Give a task back after its lane's session failed without doing anything.
#
# An expired login or a model the account cannot use ends the session at once,
# before any change. Left alone, the claim holds the task until somebody
# notices and deletes the branch by hand. The launcher runs this in the lane
# worktree when the session exits non-zero; a lane that changed anything is
# kept for a human, since only a human can tell partial work from waste.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: bash release-lane.sh [--remote <name>] <task-file>

Run from the root of the lane worktree, on branch task/<id>. When the lane left
no change and no commit past its claim, deletes the claim on the remote, then
the worktree and its local branch.

Options:
  --remote <name>   Shared remote (default: origin).
  -h, --help        Print this help.

Prints one line, tab-separated:
  RELEASED  <id>
  KEPT      <id>  <reason>

Exit codes:
  0  the claim was released
  1  usage or environment error
  3  kept: the lane left work behind, or the claim is not this lane's
USAGE
}

remote="origin"
task_file=""

while (($# > 0)); do
  case "$1" in
    --remote) [[ $# -ge 2 ]] || die "--remote requires a value"; remote="$2"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) [[ -z "$task_file" ]] || die "one task file only"; task_file="$1"; shift ;;
  esac
done

[[ -n "$task_file" ]] || die "no task file given"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"
worktree="$(git rev-parse --show-toplevel)"
[[ "$worktree" == "$(pwd -P)" ]] || die "run from the root of the lane worktree"

task_id="$(basename "$task_file" .md)"
branch="task/$task_id"
[[ "$(git symbolic-ref --short -q HEAD)" == "$branch" ]] || die "not on $branch"

if [[ -n "$(git status --porcelain)" ]]; then
  printf 'KEPT\t%s\tthe worktree has changes\n' "$task_id"
  exit 3
fi

# HEAD is the claim commit only if the lane committed nothing on top of it.
head="$(git rev-parse HEAD)"
case "$(git log -1 --format=%s HEAD)" in
  "chore(claim): task $task_id "*) ;;
  *) printf 'KEPT\t%s\tthe branch has commits past the claim\n' "$task_id"; exit 3 ;;
esac

# Delete only while the remote still points at this claim, so a branch that
# moved on, or was taken over, is never removed from under its holder.
git push -q --force-with-lease="refs/heads/$branch:$head" "$remote" ":refs/heads/$branch" 2>/dev/null ||
  { printf 'KEPT\t%s\tthe remote branch is no longer this claim\n' "$task_id"; exit 3; }

# Remove the worktree from the main checkout, or the next launch finds its path
# taken and skips the task.
main="$(cd "$(git rev-parse --git-common-dir)/.." && pwd -P)"
cd "$main"
git worktree remove "$worktree"
git branch -q -D "$branch"
printf 'RELEASED\t%s\n' "$task_id"
