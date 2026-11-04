#!/bin/sh
set -eu

# How much of each requirement merged work covers, from the requirements, the
# tasks' Covers sections and git, with nothing stored.
#
#   covered      a merged task covers it in full
#   partly       merged tasks cover it in part only
#   planned      a task covers it, and none of those is merged yet
#   not-started  no task covers it
#
# Merged means what status.sh says it means, so the two never disagree.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: sh coverage.sh [--milestone <slug>] [--tasks-dir <dir>] [--remote <name>] [--no-fetch]

Run from the repository root. Prints, tab-separated:

  REQ       <id> <state> <milestones> <merged tasks> <open tasks>
                                      one row per requirement, in the order of
                                      delivery/prd.md; a list is - when empty
  PART      <id> <task> <task state> <note>
                                      each partial cover of a requirement that
                                      is not yet covered: what that task does
  COVERAGE  covered=<n> partly=<n> planned=<n> not-started=<n>

A requirement is an outcome in delivery/prd.md written as "- **<id>.** ...".
A task covers it by listing the id under "## Covers", in full as "- <id>" or
in part as "- <id> (part): <what this task does of it>".

Options:
  --milestone <slug>  Only the requirements this milestone targets.
  --tasks-dir <dir>   Directory holding <id>.md task files (default: delivery/tasks).
  --remote <name>     Remote holding the task branches (default: origin).
  --no-fetch          Skip the remote refresh and read cached refs.
  -h, --help          Print this help.

Exit codes:
  0  coverage was read
  1  usage or environment error, including task state that cannot be read
USAGE
}

tasks_dir="delivery/tasks"
milestone=""

# Check each option once and queue the ones status.sh takes behind the rest, so
# that what is left in "$@" is exactly what status.sh receives.
remaining=$#
while [ "$remaining" -gt 0 ]; do
  case "$1" in
    --milestone)
      [ "$remaining" -ge 2 ] || die "--milestone requires a value"
      milestone="$2"; shift 2; remaining=$((remaining - 2)) ;;
    --tasks-dir)
      [ "$remaining" -ge 2 ] || die "--tasks-dir requires a value"
      tasks_dir="$2"; set -- "$@" "$1" "$2"; shift 2; remaining=$((remaining - 2)) ;;
    --remote)
      [ "$remaining" -ge 2 ] || die "--remote requires a value"
      set -- "$@" "$1" "$2"; shift 2; remaining=$((remaining - 2)) ;;
    --no-fetch) set -- "$@" "$1"; shift; remaining=$((remaining - 1)) ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

prd="$(dirname "$tasks_dir")/prd.md"
[ -f "$prd" ] || die "no requirements at $prd"

# Requirement ids, in document order: an outcome line starting "- **<id>.**".
requirements="$(awk '
  /^[-*][ \t]+\*\*[A-Za-z0-9][A-Za-z0-9-]*\.\*\*/ {
    id = $0; sub(/^[-*][ \t]+\*\*/, "", id); sub(/\.\*\*.*/, "", id); print id
  }
' "$prd")"
[ -n "$requirements" ] || die "$prd has no requirement ids: an outcome reads '- **<id>.** ...'"

# Task states and milestones come from status.sh. A plan with no task files
# yet has nothing merged and nothing planned, which is still an answer.
status_out=""
has_tasks=0
for file in "$tasks_dir"/*.md; do
  [ -e "$file" ] && has_tasks=1 && break
done
if [ "$has_tasks" -eq 1 ]; then
  status_out="$(sh "$(dirname "$0")/status.sh" "$@")" || exit $?
fi

store="$(mktemp -d)"
trap 'rm -rf "$store"' EXIT

if [ -n "$milestone" ]; then
  targets="$(printf '%s\n' "$status_out" | M="$milestone" awk -F'\t' '$1 == "MILESTONE" && $2 == ENVIRON["M"] { print $5; found = 1 } END { exit !found }')" ||
    die "no milestone '$milestone' in $(dirname "$tasks_dir")/decomposition.md"
  [ "$targets" != - ] || targets=""
fi

# One line per cover: "<requirement><TAB><task><TAB><task state><TAB>full|part<TAB><note>".
: >"$store/covers"
for file in "$tasks_dir"/*.md; do
  [ -e "$file" ] || continue
  id="$(awk '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    /^id:/ { sub(/^id:[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit }
  ' "$file")"
  [ -n "$id" ] || continue
  state="$(printf '%s\n' "$status_out" | ID="$id" awk -F'\t' '$1 == "TASK" && $2 == ENVIRON["ID"] { print $3; exit }')"
  # The Covers section: "- <id>" or "- <id> (part): <note>", where the note may
  # wrap onto indented lines.
  awk -v task="$id" -v st="${state:-unknown}" '
    function flush() { if (req != "") printf "%s\t%s\t%s\t%s\t%s\n", req, task, st, how, note; req = "" }
    /^##[[:space:]]/ { flush(); in_covers = ($0 ~ /^##[[:space:]]+Covers[[:space:]]*$/); next }
    !in_covers { next }
    /^[-*][ \t]+/ {
      flush()
      line = $0; sub(/^[-*][ \t]+/, "", line); sub(/[ \t]+$/, "", line)
      req = line; sub(/[ \t].*/, "", req)
      if (line ~ /\(part\):/) { how = "part"; note = line; sub(/^[^:]*:[ \t]*/, "", note) }
      else { how = "full"; note = "" }
      next
    }
    /^[ \t]+[^ \t]/ && req != "" { l = $0; gsub(/^[ \t]+|[ \t]+$/, "", l); note = note " " l; next }
    { flush() }
    END { flush() }
  ' "$file" >>"$store/covers"
done

milestones="$(printf '%s\n' "$status_out" | awk -F'\t' '$1 == "MILESTONE" { print $2 "\t" $5 }')"

covered=0 partly=0 planned=0 not_started=0
for req in $requirements; do
  if [ -n "$milestone" ]; then
    case " $targets " in *" $req "*) ;; *) continue ;; esac
  fi
  rows="$(REQ="$req" awk -F'\t' '$1 == ENVIRON["REQ"]' "$store/covers")"
  merged="$(printf '%s\n' "$rows" | awk -F'\t' '$3 == "done" { printf "%s%s", sep, $2; sep = "," }')"
  open="$(printf '%s\n' "$rows" | awk -F'\t' 'NF && $3 != "done" { printf "%s%s", sep, $2; sep = "," }')"
  if printf '%s\n' "$rows" | awk -F'\t' '$3 == "done" && $4 == "full" { f = 1 } END { exit !f }'; then
    state=covered; covered=$((covered + 1))
  elif [ -n "$merged" ]; then
    state=partly; partly=$((partly + 1))
  elif [ -n "$open" ]; then
    state=planned; planned=$((planned + 1))
  else
    state=not-started; not_started=$((not_started + 1))
  fi
  targeted_by="$(printf '%s\n' "$milestones" | REQ="$req" awk -F'\t' '
    NF { n = split($2, t, " "); for (i = 1; i <= n; i++) if (t[i] == ENVIRON["REQ"]) { printf "%s%s", sep, $1; sep = ","; break } }
  ')"
  printf 'REQ\t%s\t%s\t%s\t%s\t%s\n' "$req" "$state" "${targeted_by:--}" "${merged:--}" "${open:--}"
  [ "$state" != covered ] || continue
  printf '%s\n' "$rows" | awk -F'\t' -v OFS='\t' '$4 == "part" { print "PART", $1, $2, $3, $5 }'
done

printf 'COVERAGE\tcovered=%s\tpartly=%s\tplanned=%s\tnot-started=%s\n' "$covered" "$partly" "$planned" "$not_started"
