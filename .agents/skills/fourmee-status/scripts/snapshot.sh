#!/usr/bin/env bash
set -euo pipefail

# Print the state of the use case as one JSON document, for connectors that
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
usage: bash snapshot.sh [options]

Prints the use case, its epics, its tasks with their derived state and pull
request, and its documents, as one JSON document (schema 1) on stdout.

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
status_args=()

while (($# > 0)); do
  case "$1" in
    --tasks-dir) [[ $# -ge 2 ]] || die "--tasks-dir requires a value"; tasks_dir="$2"; status_args+=("$1" "$2"); shift 2 ;;
    --remote) [[ $# -ge 2 ]] || die "--remote requires a value"; status_args+=("$1" "$2"); shift 2 ;;
    --no-fetch) status_args+=("$1"); shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"
home="$(git rev-parse --show-toplevel)"
delivery="$(dirname "$tasks_dir")"

# status.sh already refuses to guess, so its failure is this script's failure.
status_out="$(bash "$(dirname "${BASH_SOURCE[0]}")/status.sh" "${status_args[@]+"${status_args[@]}"}")" ||
  exit $?

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

# One scalar frontmatter value as written: field() splits lists on commas, which
# would mangle a title. Surrounding YAML quotes are removed.
scalar() {
  local v
  v="$(awk -v key="$2" '
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
      print v; exit
    }
  ' "$1")"
  if [[ "$v" =~ ^\"(.*)\"$ || "$v" =~ ^\'(.*)\'$ ]]; then v="${BASH_REMATCH[1]}"; fi
  printf '%s' "$v"
}

# A JSON string, quotes included. Control characters other than tab and newline
# carry nothing a connector needs, so they are dropped rather than escaped.
json_str() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\t'/\\t}"
  s="${s//$'\n'/\\n}"
  s="${s//[$'\001'-$'\037']/}"
  printf '"%s"' "$s"
}

json_or_null() {
  if [[ -n "$1" ]]; then json_str "$1"; else printf 'null'; fi
}

# A space-separated list as a JSON array of strings.
json_list() {
  local item sep=""
  printf '['
  for item in $1; do
    printf '%s' "$sep"; json_str "$item"; sep=", "
  done
  printf ']'
}

join_by_comma() {
  local first=1 item
  for item in "$@"; do
    ((first == 1)) || printf ',\n'
    printf '%s' "$item"; first=0
  done
  ((first == 1)) || printf '\n'
}

# What each epic delivers, from the Epics section of the decomposition summary:
# the prose under each "### <epic>" heading, up to its task list.
declare -A delivers_of=()
epic_order=()
decomposition="$delivery/decomposition.md"
if [[ -f "$decomposition" ]]; then
  while IFS=$'\t' read -r epic text; do
    [[ -n "$epic" ]] || continue
    epic_order+=("$epic")
    delivers_of["$epic"]="$text"
  done < <(awk '
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
  ' "$decomposition")
fi

# Pull request of one task, whatever its state: the latest one on its branch.
pr_url() {
  (cd "$1" && gh pr list --head "task/$2" --state all --limit 1 --json url --jq '.[0].url // ""' 2>/dev/null) ||
    die "gh could not list pull requests in $(basename "$1"); check 'gh auth status' and the remote"
}

# status.sh reports the id a task file declares, which need not be its file name.
declare -A file_of=()
shopt -s nullglob
for file in "$tasks_dir"/*.md; do
  id="$(field "$file" id)"
  [[ -z "$id" ]] || file_of["$id"]="$file"
done
shopt -u nullglob

declare -A seen_epic=()
tasks_json=()
while IFS=$'\t' read -r kind id state holder _title; do
  [[ "$kind" == TASK ]] || continue
  file="${file_of[$id]}"
  epic="$(scalar "$file" epic)"
  repo="$(scalar "$file" repo)"
  repo_dir="$home"
  [[ -z "$repo" ]] || repo_dir="$(dirname "$home")/$repo"
  url=""
  case "$state" in in-progress | in-review | done) url="$(pr_url "$repo_dir" "$id")" ;; esac
  [[ "$holder" != "-" ]] || holder=""
  if [[ -n "$epic" && -z "${seen_epic[$epic]:-}" ]]; then
    seen_epic["$epic"]=1
    [[ -n "${delivers_of[$epic]+set}" ]] || epic_order+=("$epic")
  fi
  tasks_json+=("$(
    printf '    {"id": %s, "title": %s, "type": %s, "epic": %s, "repo": %s,\n' \
      "$(json_str "$id")" "$(json_str "$(scalar "$file" title)")" "$(json_or_null "$(scalar "$file" type)")" \
      "$(json_or_null "$epic")" "$(json_str "$(basename "$repo_dir")")"
    printf '     "state": %s, "holder": %s, "depends_on": %s,\n' \
      "$(json_str "$state")" "$(json_or_null "$holder")" "$(json_list "$(field "$file" depends_on)")"
    printf '     "pull_request": %s, "file": %s}' "$(json_or_null "$url")" "$(json_str "$file")"
  )")
done <<<"$status_out"

epics_json=()
for epic in "${epic_order[@]+"${epic_order[@]}"}"; do
  epics_json+=("$(printf '    {"id": %s, "delivers": %s}' "$(json_str "$epic")" "$(json_or_null "${delivers_of[$epic]:-}")")")
done

# The documents a reader outside git would want, with the title of each, so a
# connector can publish them without parsing markdown itself.
doc_json() {
  local title
  title="$(awk '/^#[[:space:]]/ { sub(/^#[[:space:]]+/, ""); print; exit }' "$2")"
  printf '    {"kind": %s, "path": %s, "title": %s}' "$(json_str "$1")" "$(json_str "$2")" "$(json_or_null "$title")"
}
docs_json=()
shopt -s nullglob
[[ ! -f "$delivery/prd.md" ]] || docs_json+=("$(doc_json requirements "$delivery/prd.md")")
[[ ! -f "$decomposition" ]] || docs_json+=("$(doc_json decomposition "$decomposition")")
for dir in "$delivery/decisions" docs/adr docs/decisions; do
  for doc in "$dir"/ADR-*.md; do docs_json+=("$(doc_json decision "$doc")"); done
done
for doc in "$delivery/contracts"/*.md; do docs_json+=("$(doc_json contract "$doc")"); done
shopt -u nullglob

printf '{\n'
printf '  "schema": %s,\n' "$schema"
printf '  "use_case": {"repo": %s, "commit": %s},\n' \
  "$(json_str "$(basename "$home")")" "$(json_str "$(git rev-parse HEAD)")"
printf '  "epics": [\n'; join_by_comma "${epics_json[@]+"${epics_json[@]}"}"; printf '  ],\n'
printf '  "tasks": [\n'; join_by_comma "${tasks_json[@]+"${tasks_json[@]}"}"; printf '  ],\n'
printf '  "documents": [\n'; join_by_comma "${docs_json[@]+"${docs_json[@]}"}"; printf '  ]\n'
printf '}\n'
