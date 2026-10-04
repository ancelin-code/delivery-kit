#!/bin/sh
set -eu

# Validate a decomposed task set before any lane starts.
#
# Every check here is deterministic. The cost of a bad task set is paid by
# several developers at once, hours later, so it is worth catching up front:
# a missing dependency stalls a lane, a dependency cycle stalls all of them,
# and an undeclared file conflict produces work that cannot be merged.
#
# Frontmatter is parsed as a constrained subset of YAML: one `key: value` per
# line, and lists written inline as `[a, b]`. Task files are generated from the
# template in this skill, so the subset is a contract, not a limitation.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: sh validate-tasks.sh [--tasks-dir <dir>] [--max-per-epic <n>]

Validates every task file in <dir> (default: delivery/tasks), and the
decomposition summary that has to agree with it.

Options:
  --tasks-dir <dir>     Directory holding <id>.md task files (default: delivery/tasks).
  --max-per-epic <n>    Maximum tasks allowed in one epic (default: 10).
  --decomposition <p>   Decomposition summary to cross-check (default:
                        decomposition.md beside the tasks directory, so
                        delivery/decomposition.md).
  -h, --help            Print this help.

Exit codes:
  0  every task file is valid
  1  usage or environment error
  2  at least one validation failure
USAGE
}

tasks_dir="delivery/tasks"
max_per_epic=10
decomposition=""

while [ $# -gt 0 ]; do
  case "$1" in
    --tasks-dir)
      [ $# -ge 2 ] || die "--tasks-dir requires a value"
      tasks_dir="$2"; shift 2 ;;
    --max-per-epic)
      [ $# -ge 2 ] || die "--max-per-epic requires a value"
      max_per_epic="$2"; shift 2 ;;
    --decomposition)
      [ $# -ge 2 ] || die "--decomposition requires a value"
      decomposition="$2"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    --) shift; break ;;
    -*) die "unknown option: $1" ;;
    *) die "unexpected argument: $1" ;;
  esac
done

case "$max_per_epic" in "" | *[!0-9]*) die "--max-per-epic must be a number" ;; esac
[ -d "$tasks_dir" ] || die "tasks directory not found: $tasks_dir"
# The summary is a sibling of the task set, not a child of it: it describes the
# whole cut, and a file inside tasks/ would be globbed as a task.
[ -n "$decomposition" ] || decomposition="$(dirname "$tasks_dir")/decomposition.md"

# Mirrors the tiers table in the delivery conventions, which is where a tier's
# meaning is defined. A test parses that table and fails if the two drift apart.
VALID_TIERS=" plan build chore "
VALID_TYPES=" feat fix refactor perf test docs build ci chore "

failures=0
fail() {
  printf 'FAIL\t%s\t%s\n' "$1" "$2"
  failures=$((failures + 1))
}

# Read the epic/task pairs the decomposition summary declares, as "epic<TAB>id".
# Only the Epics section is read, so prose elsewhere in the file cannot be
# mistaken for a declaration.
summary_rows() {
  awk '
    /^##[[:space:]]/ { in_epics = ($0 ~ /^##[[:space:]]+Epics[[:space:]]*$/); next }
    !in_epics { next }
    /^###[[:space:]]/ {
      epic = $0
      sub(/^###[[:space:]]+/, "", epic)
      sub(/[[:space:]]+$/, "", epic)
      next
    }
    /^-[[:space:]]+`/ {
      id = $0
      sub(/^-[[:space:]]+`/, "", id)
      sub(/`.*/, "", id)
      if (id != "" && epic != "") printf "%s\t%s\n", epic, id
    }
  ' "$1"
}

# Read one frontmatter key. Lists come back space separated.
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
      gsub(/^\[|\]$/, "", v)
      gsub(/,/, " ", v)
      gsub(/^[ \t]+|[ \t]+$/, "", v)
      print v
      exit
    }
  ' "$1"
}

# The facts pass 1 collects, one task per line, for the cross-checks in pass 2:
# "<id><TAB><epic><TAB><parallel><TAB><depends_on><TAB><conflicts_with>".
store="$(mktemp -d)"
trap 'rm -rf "$store"' EXIT
: >"$store/facts"
: >"$store/ids"

# A task's repo field names a clone beside the repository holding the tasks.
home="$(git -C "$tasks_dir" rev-parse --show-toplevel 2>/dev/null || true)"

# Pass 1: per-file shape. Collect the facts so cross-references can be checked after.
found=0
for file in "$tasks_dir"/*.md; do
  [ -e "$file" ] || continue
  found=1
  base="$(basename "$file" .md)"

  if [ "$(head -n 1 "$file")" != "---" ]; then
    fail "$base" "no frontmatter: the file must start with ---"
    continue
  fi

  id="$(field "$file" id)"
  title="$(field "$file" title)"
  epic="$(field "$file" epic)"
  tier="$(field "$file" tier)"
  type="$(field "$file" type)"
  parallel="$(field "$file" parallel)"
  depends="$(field "$file" depends_on)"
  conflicts="$(field "$file" conflicts_with)"
  repo="$(field "$file" repo)"

  [ -n "$id" ] || { fail "$base" "missing required field: id"; continue; }
  [ -n "$title" ] || fail "$base" "missing required field: title"
  [ -n "$epic" ] || fail "$base" "missing required field: epic"

  # The id is used as a branch name and a filename, so it must stay a slug.
  case "$id" in
    -* | *- | *[!a-z0-9-]*) fail "$base" "id is not a lowercase slug: '$id'" ;;
  esac

  # A mismatch silently breaks every lookup that goes through the filename.
  if [ "$id" != "$base" ]; then
    fail "$base" "id '$id' does not match the filename"
  fi

  if grep -Fxq -- "$id" "$store/ids"; then
    fail "$base" "duplicate id: '$id'"
  fi
  printf '%s\n' "$id" >>"$store/ids"

  if [ -n "$tier" ]; then
    case "$VALID_TIERS" in
      *" $tier "*) ;;
      *) fail "$base" "unknown tier: '$tier' (expected plan, build, or chore)" ;;
    esac
  else
    fail "$base" "missing required field: tier (plan, build, or chore)"
  fi

  # Optional: the commit and pull request type, feat when absent.
  if [ -n "$type" ]; then
    case "$VALID_TYPES" in
      *" $type "*) ;;
      *) fail "$base" "unknown type: '$type' (expected a Conventional Commits type such as feat, fix or refactor)" ;;
    esac
  fi

  # Optional: the repository the change lands in, when it is not this one. A
  # missing clone would only surface when the lane launches, on someone else's
  # machine, so it is caught here.
  if [ -n "$repo" ]; then
    case "$repo" in
      . | .. | *[!A-Za-z0-9._-]*)
        fail "$base" "repo must be the directory name of a sibling clone, got '$repo'"
        ;;
      *)
        if [ -n "$home" ] && ! git -C "$(dirname "$home")/$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
          fail "$base" "repo '$repo' has no clone at $(dirname "$home")/$repo; clone it beside $(basename "$home")"
        fi
        ;;
    esac
  fi

  case "$parallel" in
    "" | true | false) ;;
    *) fail "$base" "parallel must be true or false, got '$parallel'" ;;
  esac

  # A task without observable acceptance criteria cannot be verified as done.
  if ! grep -qiE '^#+[[:space:]]*acceptance criteria' "$file"; then
    fail "$base" "no 'Acceptance criteria' heading in the body"
  fi

  printf '%s\t%s\t%s\t%s\t%s\n' "$id" "$epic" "$parallel" "$depends" "$conflicts" >>"$store/facts"
done

[ "$found" -eq 1 ] || die "no task files found in $tasks_dir"

# The summary's declarations, for the cross-check against the task files.
: >"$store/declared"
summary_name="$(basename "$decomposition")"
has_summary=0
run_as=""
if [ -f "$decomposition" ]; then
  has_summary=1
  summary_rows "$decomposition" >"$store/declared"
  run_as="$(grep -m1 '^\*\*Run as:\*\*' "$decomposition" || true)"
fi

# Passes 2 to 5 compare tasks with each other, which is what awk is for.
#
# Pass 2: cross-references.
# Pass 3: dependency cycles, by repeatedly resolving tasks whose dependencies
#         are all resolved. Whatever stays unresolved is part of a cycle.
# Pass 4: epic size. An epic past the cap is a decomposition that was not
#         finished, and it makes the dependency graph hard to reason about.
# Pass 5: the decomposition summary. Decomposition also produces the grouping,
#         the serialization points and the critical path, and those are
#         reasoning, not something derivable from the task files. Without a
#         file they die with the session that produced them and the approval
#         gate has nothing to read.
checks="$(RUN_AS="$run_as" SUMMARY="$summary_name" SUMMARY_PATH="$decomposition" HAS_SUMMARY="$has_summary" \
  awk -F'\t' -v max="$max_per_epic" -v facts="$store/facts" '
  function fail(who, why) { printf "FAIL\t%s\t%s\n", who, why }
  FILENAME == facts {
    # one line per task file
    if (!($1 in seen)) { ids[++n] = $1; seen[$1] = 1 }
    epic_of[$1] = $2; parallel_of[$1] = $3; depends_of[$1] = $4; conflicts_of[$1] = $5
    if ($2 != "") {
      if (!($2 in epic_count)) { epics[++e] = $2 }
      epic_count[$2]++
    }
    next
  }
  { declared_ids[++d] = $2; declared_epic[$2] = $1 }
  END {
    for (i = 1; i <= n; i++) {
      id = ids[i]
      k = split(depends_of[id], deps, " ")
      for (j = 1; j <= k; j++) {
        if (!(deps[j] in seen)) fail(id, "depends_on references an unknown task: \047" deps[j] "\047")
        if (deps[j] == id) fail(id, "depends_on lists itself")
      }
      k = split(conflicts_of[id], others, " ")
      for (j = 1; j <= k; j++) {
        if (!(others[j] in seen)) fail(id, "conflicts_with references an unknown task: \047" others[j] "\047")
        if (others[j] == id) fail(id, "conflicts_with lists itself")
      }
    }

    progress = 1
    while (progress) {
      progress = 0
      for (i = 1; i <= n; i++) {
        id = ids[i]
        if (id in resolved) continue
        ok = 1
        k = split(depends_of[id], deps, " ")
        for (j = 1; j <= k; j++)
          if ((deps[j] in seen) && !(deps[j] in resolved)) { ok = 0; break }
        if (ok) { resolved[id] = 1; progress = 1 }
      }
    }
    cycle = ""
    for (i = 1; i <= n; i++) if (!(ids[i] in resolved)) cycle = cycle (cycle == "" ? "" : " ") ids[i]
    if (cycle != "") fail(cycle, "dependency cycle: these tasks can never become ready")

    for (i = 1; i <= e; i++)
      if (epic_count[epics[i]] > max)
        fail(epics[i], "epic holds " epic_count[epics[i]] " tasks, more than the " max " allowed")

    summary = ENVIRON["SUMMARY"]
    if (ENVIRON["HAS_SUMMARY"] != 1) {
      fail(summary, "no decomposition summary at " ENVIRON["SUMMARY_PATH"])
    } else {
      # Both directions matter. A task in the summary with no file is a lane that
      # can never start; a task file absent from the summary is work nobody
      # approved, which a launcher would happily run anyway.
      for (i = 1; i <= d; i++) {
        id = declared_ids[i]
        if (!(id in seen)) fail(summary, "lists a task with no file: \047" id "\047")
        else if (declared_epic[id] != epic_of[id])
          fail(id, "epic is \047" epic_of[id] "\047 in the task file, \047" declared_epic[id] "\047 in " summary)
      }
      for (i = 1; i <= n; i++)
        if (!(ids[i] in declared_epic)) fail(ids[i], "missing from " summary)

      # The launcher reads the fields, not the summary, so the two must agree: a
      # set the summary calls serial runs one lane at a time only if every task
      # says so.
      alone = 0
      for (i = 1; i <= n; i++) if (parallel_of[ids[i]] == "false") alone++
      run_as = ENVIRON["RUN_AS"]
      if (run_as ~ /\|/) fail(summary, "Run as still reads \047lanes | serially\047: pick one")
      else if (run_as ~ /serial/) {
        for (i = 1; i <= n; i++)
          if (parallel_of[ids[i]] != "false")
            fail(ids[i], summary " runs the set serially, so parallel must be false")
      } else if (run_as ~ /lanes/) {
        if (n > 1 && alone == n) fail(summary, "every task runs alone, so Run as should say serially")
      } else fail(summary, "no \047Run as:\047 line saying lanes or serially")
    }
    printf "TASKS\t%s\n", n
    printf "EPICS\t%s\n", e
  }
' "$store/facts" "$store/declared")"

printf '%s\n' "$checks"
failures=$((failures + $(printf '%s\n' "$checks" | grep -c '^FAIL' || true)))

if [ "$failures" -gt 0 ]; then
  printf 'RESULT\tinvalid\n'
  printf 'FAILURES\t%s\n' "$failures"
  exit 2
fi

printf 'RESULT\tvalid\n'
