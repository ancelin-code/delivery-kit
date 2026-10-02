#!/usr/bin/env bash
set -euo pipefail

# Fail early and clearly on an older bash, such as the 3.2 macOS ships.
if ((BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4))); then
  printf 'ERROR\tbash 4.4 or later is required, found %s\n' "$BASH_VERSION" >&2
  exit 1
fi

# A stand-up view of the run: who is on what, what is free to pick up, and what
# is waiting. Same derivation as status.sh, grouped for reading aloud.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: bash standup.sh [--tasks-dir <dir>] [--remote <name>] [--no-fetch]

Prints the run state grouped by what a stand-up needs to decide.
USAGE
}

args=()
while (($# > 0)); do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --tasks-dir | --remote)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      args+=("$1" "$2"); shift 2 ;;
    --no-fetch) args+=("$1"); shift ;;
    *) die "unknown option: $1" ;;
  esac
done

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rows="$(bash "$here/status.sh" "${args[@]+"${args[@]}"}")"

section() {
  local state="$1" heading="$2" body
  body="$(printf '%s\n' "$rows" | awk -F'\t' -v s="$state" '$1=="TASK" && $3==s')"
  [[ -n "$body" ]] || return 0
  printf '%s\n' "$heading"
  printf '%s\n' "$body" | awk -F'\t' '{
    if ($4 != "-") printf "  %-22s %s  (%s)\n", $2, $5, $4
    else           printf "  %-22s %s\n", $2, $5
  }'
  printf '\n'
}

printf '%s\n' "$rows" | awk -F'\t' '$1=="NOTE" { printf "note: %s\n\n", $2 }'

section "in-review"   "Waiting on a reviewer"
section "in-progress" "In progress"
section "ready"       "Ready to pick up"
section "blocked"     "Blocked on a dependency"
section "done"        "Done"

printf '%s\n' "$rows" | awk -F'\t' '$1=="SUMMARY" {
  for (i = 2; i <= NF; i++) printf "%s%s", $i, (i < NF ? "  " : "\n")
}'
