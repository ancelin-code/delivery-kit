#!/bin/sh
set -eu

# A stand-up view of the run: who is on what, what is free to pick up, and what
# is waiting. Same derivation as status.sh, grouped for reading aloud.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: sh standup.sh [--tasks-dir <dir>] [--remote <name>] [--no-fetch]

Prints the run state grouped by what a stand-up needs to decide.
USAGE
}

# Check each option once and queue the accepted ones behind the rest, so that
# what is left in "$@" is exactly what status.sh receives.
remaining=$#
while [ "$remaining" -gt 0 ]; do
  case "$1" in
    -h | --help) usage; exit 0 ;;
    --tasks-dir | --remote)
      [ "$remaining" -ge 2 ] || die "$1 requires a value"
      set -- "$@" "$1" "$2"; shift 2; remaining=$((remaining - 2)) ;;
    --no-fetch) set -- "$@" "$1"; shift; remaining=$((remaining - 1)) ;;
    *) die "unknown option: $1" ;;
  esac
done

here="$(cd "$(dirname "$0")" && pwd)"
rows="$(sh "$here/status.sh" "$@")"

# section <state> <heading>: the rows in that state, under a heading.
section() (
  body="$(printf '%s\n' "$rows" | awk -F'\t' -v s="$1" '$1=="TASK" && $3==s')"
  [ -n "$body" ] || return 0
  printf '%s\n' "$2"
  printf '%s\n' "$body" | awk -F'\t' '{
    if ($4 != "-") printf "  %-22s %s  (%s)\n", $2, $5, $4
    else           printf "  %-22s %s\n", $2, $5
  }'
  printf '\n'
)

printf '%s\n' "$rows" | awk -F'\t' '$1=="NOTE" { printf "note: %s\n\n", $2 }'

section "in-review"   "Waiting on a reviewer"
section "in-progress" "In progress"
section "ready"       "Ready to pick up"
section "blocked"     "Blocked on a dependency"
section "done"        "Done"

printf '%s\n' "$rows" | awk -F'\t' '$1=="SUMMARY" {
  for (i = 2; i <= NF; i++) printf "%s%s", $i, (i < NF ? "  " : "\n")
}'
