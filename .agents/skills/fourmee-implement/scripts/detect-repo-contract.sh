#!/usr/bin/env bash
set -euo pipefail

# Fail early and clearly on an older bash, such as the 3.2 macOS ships.
if ((BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4))); then
  printf 'ERROR\tbash 4.4 or later is required, found %s\n' "$BASH_VERSION" >&2
  exit 1
fi

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

instruction_file=""
for candidate in AGENTS.md CLAUDE.md .github/copilot-instructions.md; do
  if [[ -f "$candidate" ]]; then
    instruction_file="$candidate"
    break
  fi
done
printf 'INSTRUCTIONS\t%s\n' "${instruction_file:-none}"

runner=""
if [[ -f mise.toml ]]; then
  runner="mise"
elif [[ -f noxfile.py ]]; then
  runner="nox"
elif [[ -f Makefile ]]; then
  runner="make"
elif [[ -f package.json ]]; then
  runner="npm"
elif [[ -f pyproject.toml ]]; then
  runner="pyproject"
fi
printf 'RUNNER\t%s\n' "${runner:-none}"

# Each branch collects into $tasks (newline-separated) without letting an empty match
# abort the script under `set -e pipefail`.
tasks=""
case "$runner" in
  mise)
    if command -v mise >/dev/null 2>&1; then
      tasks="$(mise tasks --json 2>/dev/null \
        | grep -o '"name":[[:space:]]*"[^"]*"' \
        | sed -E 's/"name":[[:space:]]*"//; s/"$//' || true)"
    fi
    ;;
  nox)
    if command -v nox >/dev/null 2>&1; then
      tasks="$(nox --list 2>/dev/null | grep -E '^\* ' | sed 's/^\* //' || true)"
    fi
    ;;
  make)
    tasks="$(grep -E '^[A-Za-z0-9_-]+:' Makefile 2>/dev/null | cut -d: -f1 | sort -u || true)"
    ;;
  npm)
    if command -v node >/dev/null 2>&1; then
      tasks="$(node -e "const s=require('./package.json').scripts||{};for(const k of Object.keys(s))console.log(k)" 2>/dev/null || true)"
    fi
    ;;
esac
if [[ -n "$tasks" ]]; then
  while IFS= read -r task; do
    [[ -n "$task" ]] && printf 'TASK\t%s\n' "$task"
  done <<<"$tasks"
fi

if [[ -f CODEOWNERS ]]; then
  printf 'CODEOWNERS\t%s\n' "CODEOWNERS"
elif [[ -f .github/CODEOWNERS ]]; then
  printf 'CODEOWNERS\t%s\n' ".github/CODEOWNERS"
elif [[ -f docs/CODEOWNERS ]]; then
  printf 'CODEOWNERS\t%s\n' "docs/CODEOWNERS"
else
  printf 'CODEOWNERS\tnone\n'
fi

branch_samples="$(git for-each-ref --sort=-committerdate --format='%(refname:short)' refs/heads/ refs/remotes/origin/ 2>/dev/null \
  | { grep -v -E '^(origin/)?(HEAD|main|master|develop)$' || true; } | awk '!seen[$0]++' | head -8)"
if [[ -n "$branch_samples" ]]; then
  while IFS= read -r b; do
    printf 'BRANCH_SAMPLE\t%s\n' "$b"
  done <<<"$branch_samples"
else
  printf 'BRANCH_SAMPLE\tnone\n'
fi

commit_samples="$(git log --format='%s' -n 10 2>/dev/null || true)"
if [[ -n "$commit_samples" ]]; then
  while IFS= read -r c; do
    printf 'COMMIT_SAMPLE\t%s\n' "$c"
  done <<<"$commit_samples"
else
  printf 'COMMIT_SAMPLE\tnone\n'
fi
