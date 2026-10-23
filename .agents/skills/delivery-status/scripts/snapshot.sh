#!/bin/sh
set -eu

# Print the state of the project as one JSON document, for connectors that
# project it into an external tool such as Jira or Confluence. The contract
# those connectors follow is ADR-005 in the kit's repository.
#
# States come from status.sh, so a snapshot and a status read never disagree.
# Nothing here writes anything.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: sh snapshot.sh [options]

Prints the project, its milestones, its epics, its tasks with their derived
state and pull request, the coverage of its requirements, and its documents,
as one JSON document (schema 1) on stdout. A project without milestones, or
whose requirements carry no ids, has an empty list for them.

Options:
  --tasks-dir <dir>   Directory holding <id>.md task files (default: delivery/tasks).
  --remote <name>     Remote holding the task branches (default: origin).
  --no-fetch          Skip the remote refresh and read cached refs.
  -h, --help          Print this help.
USAGE
}

# Raise on any change a connector could break on: a renamed or removed field, a
# new state value. Adding a field does not need it.
schema=1
tasks_dir="delivery/tasks"

# Check each option once and queue the accepted ones behind the rest, so that
# what is left in "$@" is exactly what status.sh receives.
remaining=$#
while [ "$remaining" -gt 0 ]; do
  case "$1" in
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

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"
home="$(git rev-parse --show-toplevel)"
delivery="$(dirname "$tasks_dir")"
tab="$(printf '\t')"

# status.sh already refuses to guess, so its failure is this script's failure.
status_out="$(sh "$(dirname "$0")/status.sh" "$@")" ||
  exit $?

# Lists of JSON items are files, one item per entry, and "file_of" is a
# directory with one file per task id: POSIX sh has no arrays to hold them.
store="$(mktemp -d)"
trap 'rm -rf "$store"' EXIT
mkdir "$store/file_of"

# add <list> <json>: append one item to a list, comma-separated.
add() {
  [ ! -s "$store/$1" ] || printf ',\n' >>"$store/$1"
  printf '%s' "$2" >>"$store/$1"
}

# print_list <list>: the items of a list, one per line, commas between them.
print_list() {
  [ ! -s "$store/$1" ] || { cat "$store/$1"; printf '\n'; }
}

# The frontmatter value of one key. field() splits a list on commas and spaces;
# scalar() keeps the value as written, so a title keeps its commas, and removes
# surrounding YAML quotes.
frontmatter() {
  awk -v key="$2" -v mode="$3" '
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
      if (mode == "list") {
        gsub(/^\[|\]$/, "", v); gsub(/,/, " ", v)
        gsub(/^[ \t]+|[ \t]+$/, "", v)
      } else if (v ~ /^".*"$/ || v ~ /^\047.*\047$/) {
        v = substr(v, 2, length(v) - 2)
      }
      print v; exit
    }
  ' "$1"
}
field() { frontmatter "$1" "$2" list; }
scalar() { frontmatter "$1" "$2" scalar; }

# A JSON string, quotes included. Control characters other than tab and newline
# carry nothing a connector needs, so they are dropped rather than escaped. The
# value travels in the environment because awk -v would read its backslashes.
json_str() {
  S="$1" awk 'BEGIN {
    s = ENVIRON["S"]; out = ""
    for (i = 1; i <= length(s); i++) {
      c = substr(s, i, 1)
      if (c == "\\") out = out "\\\\"
      else if (c == "\"") out = out "\\\""
      else if (c == "\t") out = out "\\t"
      else if (c == "\n") out = out "\\n"
      else if (c >= " ") out = out c
    }
    printf "\"%s\"", out
  }'
}

json_or_null() {
  if [ -n "$1" ]; then json_str "$1"; else printf 'null'; fi
}

# A space-separated list as a JSON array of strings.
json_list() (
  sep=""
  printf '['
  for item in $1; do
    printf '%s' "$sep"; json_str "$item"; sep=", "
  done
  printf ']'
)

# What each epic delivers, from the Epics section of the decomposition summary:
# the prose under each "### <epic>" heading, up to its task list. The epics file
# holds one "<epic><TAB><delivers>" line per epic, in the order they are printed.
decomposition="$delivery/decomposition.md"
: >"$store/epics"
if [ -f "$decomposition" ]; then
  awk '
    function flush() { if (epic != "") { gsub(/^ +| +$/, "", text); printf "%s\t%s\n", epic, text } }
    /^##[[:space:]]/ && !/^###/ { flush(); epic = ""; in_epics = ($0 ~ /^##[[:space:]]+Epics[[:space:]]*$/); next }
    !in_epics { next }
    /^###[[:space:]]/ {
      flush()
      epic = $0; sub(/^###[[:space:]]+/, "", epic); sub(/[[:space:]]+$/, "", epic)
      text = ""; listing = 0; next
    }
    epic == "" { next }
    /^-[[:space:]]/ { listing = 1; next }
    !listing && NF { gsub(/\t/, " "); text = text " " $0 }
    END { flush() }
  ' "$decomposition" >"$store/epics"
fi

# epic_delivers <epic>: the text, empty when there is none. epic_known <epic>.
epic_delivers() {
  K="$1" awk -F'\t' '$1 == ENVIRON["K"] { print substr($0, length($1) + 2); exit }' "$store/epics"
}
epic_known() {
  K="$1" awk -F'\t' '$1 == ENVIRON["K"] { found = 1 } END { exit !found }' "$store/epics"
}

# Pull request of one task, whatever its state: the latest one on its branch.
pr_url() {
  (cd "$1" && gh pr list --head "task/$2" --state all --limit 1 --json url --jq '.[0].url // ""' 2>/dev/null) ||
    die "gh could not list pull requests in $(basename "$1"); check 'gh auth status' and the remote"
}

# status.sh reports the id a task file declares, which need not be its file name.
for file in "$tasks_dir"/*.md; do
  [ -e "$file" ] || continue
  id="$(field "$file" id)"
  [ -z "$id" ] || printf '%s' "$file" >"$store/file_of/$id"
done

while IFS="$tab" read -r kind id state holder _title; do
  [ "$kind" = TASK ] || continue
  file="$(cat "$store/file_of/$id")"
  epic="$(scalar "$file" epic)"
  repo="$(scalar "$file" repo)"
  repo_dir="$home"
  [ -z "$repo" ] || repo_dir="$(dirname "$home")/$repo"
  url=""
  case "$state" in in-progress | in-review | done) url="$(pr_url "$repo_dir" "$id")" ;; esac
  [ "$holder" != "-" ] || holder=""
  if [ -n "$epic" ] && ! epic_known "$epic"; then
    printf '%s\t\n' "$epic" >>"$store/epics"
  fi
  add tasks_json "$(
    printf '    {"id": %s, "title": %s, "type": %s, "epic": %s, "repo": %s,\n' \
      "$(json_str "$id")" "$(json_str "$(scalar "$file" title)")" "$(json_or_null "$(scalar "$file" type)")" \
      "$(json_or_null "$epic")" "$(json_str "$(basename "$repo_dir")")"
    printf '     "state": %s, "holder": %s, "depends_on": %s,\n' \
      "$(json_str "$state")" "$(json_or_null "$holder")" "$(json_list "$(field "$file" depends_on)")"
    printf '     "pull_request": %s, "file": %s}' "$(json_or_null "$url")" "$(json_str "$file")"
  )"
done <<EOF_STATUS
$status_out
EOF_STATUS

while IFS="$tab" read -r epic _; do
  add epics_json "$(printf '    {"id": %s, "delivers": %s}' "$(json_str "$epic")" "$(json_or_null "$(epic_delivers "$epic")")")"
done <"$store/epics"

# Milestones, in plan order, with the state status.sh derives and the exit
# line from the decomposition summary, which may wrap.
: >"$store/exits"
if [ -f "$decomposition" ]; then
  awk '
    function flush() { if (slug != "" && text != "") { gsub(/^ +| +$/, "", text); printf "%s\t%s\n", slug, text } }
    /^##[[:space:]]/ { flush(); slug = ""; in_plan = ($0 ~ /^##[[:space:]]+Milestones[[:space:]]*$/); next }
    !in_plan { next }
    /^###[[:space:]]/ { flush(); slug = $0; sub(/^###[[:space:]]+/, "", slug); sub(/[[:space:]]+$/, "", slug); text = ""; open = 0; next }
    /^\*\*Exit:\*\*/ { text = $0; sub(/^\*\*Exit:\*\*[ \t]*/, "", text); open = 1; next }
    /^[ \t]*$/ || /^\*\*/ { open = 0; next }
    open { gsub(/\t/, " "); text = text " " $0 }
    END { flush() }
  ' "$decomposition" >"$store/exits"
fi
while IFS="$tab" read -r kind slug state epics targets; do
  [ "$kind" = MILESTONE ] || continue
  [ "$epics" != - ] || epics=""
  [ "$targets" != - ] || targets=""
  exit_text="$(K="$slug" awk -F'\t' '$1 == ENVIRON["K"] { print substr($0, length($1) + 2); exit }' "$store/exits")"
  add milestones_json "$(
    printf '    {"id": %s, "state": %s, "exit": %s,\n' \
      "$(json_str "$slug")" "$(json_str "$state")" "$(json_or_null "$exit_text")"
    printf '     "epics": %s, "requirements": %s}' "$(json_list "$epics")" "$(json_list "$targets")"
  )"
done <<EOF_MILESTONES
$status_out
EOF_MILESTONES

# Coverage of each requirement, as coverage.sh reports it, when the
# requirements carry ids. Its failure is this script's failure, as status.sh's is.
if [ -f "$delivery/prd.md" ] && grep -Eq '^[-*][[:space:]]+\*\*[A-Za-z0-9][A-Za-z0-9-]*\.\*\*' "$delivery/prd.md"; then
  coverage_out="$(sh "$(dirname "$0")/coverage.sh" "$@")" || exit $?
  # comma lists, "-" when empty, as JSON arrays
  csv_list() { if [ "$1" = - ]; then printf '[]'; else json_list "$(printf '%s' "$1" | tr ',' ' ')"; fi; }
  while IFS="$tab" read -r kind req state milestones merged open; do
    [ "$kind" = REQ ] || continue
    parts=""
    while IFS="$tab" read -r pkind preq ptask pstate pnote; do
      [ "$pkind" = PART ] && [ "$preq" = "$req" ] || continue
      parts="${parts:+$parts, }$(printf '{"task": %s, "state": %s, "note": %s}' \
        "$(json_str "$ptask")" "$(json_str "$pstate")" "$(json_str "$pnote")")"
    done <<EOF_PARTS
$coverage_out
EOF_PARTS
    add requirements_json "$(
      printf '    {"id": %s, "state": %s, "milestones": %s,\n' \
        "$(json_str "$req")" "$(json_str "$state")" "$(csv_list "$milestones")"
      printf '     "merged": %s, "open": %s, "parts": [%s]}' "$(csv_list "$merged")" "$(csv_list "$open")" "$parts"
    )"
  done <<EOF_COVERAGE
$coverage_out
EOF_COVERAGE
fi

# The documents a reader outside git would want, with the title of each, so a
# connector can publish them without parsing markdown itself.
add_doc() {
  title="$(awk '/^#[[:space:]]/ { sub(/^#[[:space:]]+/, ""); print; exit }' "$2")"
  add docs_json "$(printf '    {"kind": %s, "path": %s, "title": %s}' "$(json_str "$1")" "$(json_str "$2")" "$(json_or_null "$title")")"
}
[ ! -f "$delivery/prd.md" ] || add_doc requirements "$delivery/prd.md"
[ ! -f "$decomposition" ] || add_doc decomposition "$decomposition"
for dir in "$delivery/decisions" docs/adr docs/decisions; do
  for doc in "$dir"/ADR-*.md; do
    [ ! -e "$doc" ] || add_doc decision "$doc"
  done
done
for doc in "$delivery/contracts"/*.md; do
  [ ! -e "$doc" ] || add_doc contract "$doc"
done

printf '{\n'
printf '  "schema": %s,\n' "$schema"
printf '  "use_case": {"repo": %s, "commit": %s},\n' \
  "$(json_str "$(basename "$home")")" "$(json_str "$(git rev-parse HEAD)")"
printf '  "milestones": [\n'; print_list milestones_json; printf '  ],\n'
printf '  "epics": [\n'; print_list epics_json; printf '  ],\n'
printf '  "tasks": [\n'; print_list tasks_json; printf '  ],\n'
printf '  "requirements": [\n'; print_list requirements_json; printf '  ],\n'
printf '  "documents": [\n'; print_list docs_json; printf '  ]\n'
printf '}\n'
