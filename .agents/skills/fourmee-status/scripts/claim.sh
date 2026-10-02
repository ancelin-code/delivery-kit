#!/usr/bin/env bash
set -euo pipefail

# Fail early and clearly on an older bash, such as the 3.2 macOS ships.
if ((BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4))); then
  printf 'ERROR\tbash 4.4 or later is required, found %s\n' "$BASH_VERSION" >&2
  exit 1
fi

# Claim a task by creating the remote branch task/<id>.
#
# The claim is the branch creation itself: git applies ref creation atomically,
# so the first push wins. The pushed commit must differ from every other
# developer's, otherwise git resolves the push as "Everything up-to-date" and
# exits 0 for a task somebody else already holds. The claim commit provides
# that difference and records who claimed the task and when.
#
# The commit is built with `git commit-tree`, so the local branch is untouched
# until the claim is won and a lost race needs no cleanup.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: bash claim.sh [--remote <name>] [--no-advance] <task-id>

Claims <task-id> by creating the remote branch task/<task-id>.

Options:
  --remote <name>   Remote holding the task branches (default: origin).
  --no-advance      Leave the local branch where it is after a won claim.
  -h, --help        Print this help.

Exit codes:
  0  claim won
  1  usage, environment, or unexpected git error
  2  task already claimed by somebody else
USAGE
}

remote="origin"
advance=1
task_id=""

while (($# > 0)); do
  case "$1" in
    --remote)
      [[ $# -ge 2 ]] || die "--remote requires a value"
      remote="$2"
      shift 2
      ;;
    --no-advance)
      advance=0
      shift
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      die "unknown option: $1"
      ;;
    *)
      [[ -z "$task_id" ]] || die "unexpected argument: $1"
      task_id="$1"
      shift
      ;;
  esac
done

# Positional arguments left after an explicit `--` separator.
if [[ -z "$task_id" && $# -gt 0 ]]; then
  task_id="$1"
  shift
fi
(($# == 0)) || die "unexpected argument: $1"

[[ -n "$task_id" ]] || {
  usage >&2
  exit 1
}

# Task ids are epic-scoped slugs such as "ingestion-003". Rejecting anything
# else keeps the id usable as a branch name and as a filename.
[[ "$task_id" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] ||
  die "invalid task id: '$task_id' (expected a lowercase slug, e.g. ingestion-003)"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
  die "not inside a git repository"

git remote get-url "$remote" >/dev/null 2>&1 ||
  die "remote '$remote' is not configured"

branch="task/$task_id"
ref="refs/heads/$branch"

head_commit="$(git rev-parse HEAD 2>/dev/null)" ||
  die "HEAD does not resolve to a commit; commit something before claiming"
tree="$(git rev-parse 'HEAD^{tree}')"

claimant="$(git config user.name || true)"
[[ -n "$claimant" ]] || die "git user.name is not set; a claim must identify its owner"

# Build the claim commit without moving any local ref.
claim_commit="$(
  git commit-tree "$tree" -p "$head_commit" \
    -m "chore(claim): task $task_id [$claimant]"
)"

push_log=""
push_rc=0
push_log="$(
  git push --force-with-lease="$ref:" "$remote" "$claim_commit:$ref" 2>&1
)" || push_rc=$?

if ((push_rc == 0)); then
  printf 'CLAIMED\t%s\n' "$task_id"
  printf 'BRANCH\t%s\n' "$branch"
  printf 'COMMIT\t%s\n' "$claim_commit"
  printf 'CLAIMANT\t%s\n' "$claimant"

  if ((advance == 1)) && [[ "$(git branch --show-current 2>/dev/null || true)" == "$branch" ]]; then
    if [[ -n "$(git status --porcelain)" ]]; then
      printf 'NOTE\t%s\n' "local branch left in place: worktree has uncommitted changes"
    else
      git reset --hard --quiet "$claim_commit"
      printf 'ADVANCED\t%s\n' "$branch"
    fi
  fi
  exit 0
fi

# The push failed. Distinguish "somebody else holds it" from a real error.
remote_ref="$(git ls-remote --heads "$remote" "$ref" 2>/dev/null | awk 'NR==1{print $1}')"

if [[ -n "$remote_ref" ]]; then
  holder=""
  if git fetch --quiet "$remote" "$ref" 2>/dev/null; then
    holder="$(git log -1 --format='%an\t%ar' FETCH_HEAD 2>/dev/null || true)"
  fi
  printf 'HELD\t%s\n' "$task_id"
  printf 'BRANCH\t%s\n' "$branch"
  if [[ -n "$holder" ]]; then
    printf 'HOLDER\t%b\n' "$holder"
  fi
  printf 'HINT\t%s\n' "pick another ready task"
  exit 2
fi

printf '%s\n' "$push_log" >&2
die "push to '$remote' failed and $branch does not exist; see the error above"
