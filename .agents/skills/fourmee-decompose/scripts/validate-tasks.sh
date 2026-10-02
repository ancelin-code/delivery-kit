#!/usr/bin/env bash
set -euo pipefail

# Fail early and clearly on an older bash, such as the 3.2 macOS ships.
if ((BASH_VERSINFO[0] < 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] < 4))); then
  printf 'ERROR\tbash 4.4 or later is required, found %s\n' "$BASH_VERSION" >&2
  exit 1
fi

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
usage: bash validate-tasks.sh [--tasks-dir <dir>] [--max-per-epic <n>]

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

while (($# > 0)); do
  case "$1" in
    --tasks-dir)
      [[ $# -ge 2 ]] || die "--tasks-dir requires a value"
      tasks_dir="$2"; shift 2 ;;
    --max-per-epic)
      [[ $# -ge 2 ]] || die "--max-per-epic requires a value"
      max_per_epic="$2"; shift 2 ;;
    --decomposition)
      [[ $# -ge 2 ]] || die "--decomposition requires a value"
      decomposition="$2"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    --) shift; break ;;
    -*) die "unknown option: $1" ;;
    *) die "unexpected argument: $1" ;;
  esac
done

[[ "$max_per_epic" =~ ^[0-9]+$ ]] || die "--max-per-epic must be a number"
[[ -d "$tasks_dir" ]] || die "tasks directory not found: $tasks_dir"
# The summary is a sibling of the task set, not a child of it: it describes the
# whole cut, and a file inside tasks/ would be globbed as a task.
[[ -n "$decomposition" ]] || decomposition="$(dirname "$tasks_dir")/decomposition.md"

# Mirrors the model labels table in the delivery conventions, which is where a
# label's meaning is defined. A test parses that table and fails if the two
# drift apart.
VALID_MODELS=" opus sonnet terra luna haiku "

# The levels both harnesses accept. Copilot CLI also takes none and minimal,
# which Claude Code rejects; a task carrying one of those would validate here
# and then fail at launch on one side only.
VALID_EFFORTS=" low medium high xhigh max "
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

shopt -s nullglob
task_files=("$tasks_dir"/*.md)
shopt -u nullglob

((${#task_files[@]} > 0)) || die "no task files found in $tasks_dir"

# Pass 1: per-file shape. Collect ids so cross-references can be checked after.
declare -A seen_id=()
declare -A depends_of=()
declare -A conflicts_of=()
declare -A epic_count=()
declare -A epic_of=()
declare -A parallel_of=()

# A task's repo field names a clone beside the repository holding the tasks.
home="$(git -C "$tasks_dir" rev-parse --show-toplevel 2>/dev/null || true)"

for file in "${task_files[@]}"; do
  base="$(basename "$file" .md)"

  if [[ "$(head -n 1 "$file")" != "---" ]]; then
    fail "$base" "no frontmatter: the file must start with ---"
    continue
  fi

  id="$(field "$file" id)"
  title="$(field "$file" title)"
  epic="$(field "$file" epic)"
  model="$(field "$file" model)"
  effort="$(field "$file" effort)"
  type="$(field "$file" type)"
  parallel="$(field "$file" parallel)"
  depends="$(field "$file" depends_on)"
  conflicts="$(field "$file" conflicts_with)"
  repo="$(field "$file" repo)"

  [[ -n "$id" ]] || { fail "$base" "missing required field: id"; continue; }
  [[ -n "$title" ]] || fail "$base" "missing required field: title"
  [[ -n "$epic" ]] || fail "$base" "missing required field: epic"

  # The id is used as a branch name and a filename, so it must stay a slug.
  if [[ ! "$id" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]]; then
    fail "$base" "id is not a lowercase slug: '$id'"
  fi

  # A mismatch silently breaks every lookup that goes through the filename.
  if [[ "$id" != "$base" ]]; then
    fail "$base" "id '$id' does not match the filename"
  fi

  if [[ -n "${seen_id[$id]:-}" ]]; then
    fail "$base" "duplicate id: '$id'"
  fi
  seen_id["$id"]=1

  if [[ -n "$model" && "$VALID_MODELS" != *" $model "* ]]; then
    fail "$base" "unknown model label: '$model' (expected opus, sonnet, terra, luna, or haiku)"
  fi
  [[ -n "$model" ]] || fail "$base" "missing required field: model"

  # Optional: a task with no effort runs at the launcher's default.
  if [[ -n "$effort" && "$VALID_EFFORTS" != *" $effort "* ]]; then
    fail "$base" "unknown effort: '$effort' (expected low, medium, high, xhigh, or max)"
  fi

  # Optional: the commit and pull request type, feat when absent.
  if [[ -n "$type" && "$VALID_TYPES" != *" $type "* ]]; then
    fail "$base" "unknown type: '$type' (expected a Conventional Commits type such as feat, fix or refactor)"
  fi

  # Optional: the repository the change lands in, when it is not this one. A
  # missing clone would only surface when the lane launches, on someone else's
  # machine, so it is caught here.
  if [[ -n "$repo" ]]; then
    if [[ ! "$repo" =~ ^[A-Za-z0-9._-]+$ || "$repo" == . || "$repo" == .. ]]; then
      fail "$base" "repo must be the directory name of a sibling clone, got '$repo'"
    elif [[ -n "$home" ]] && ! git -C "$(dirname "$home")/$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      fail "$base" "repo '$repo' has no clone at $(dirname "$home")/$repo; clone it beside $(basename "$home")"
    fi
  fi

  if [[ -n "$parallel" && "$parallel" != "true" && "$parallel" != "false" ]]; then
    fail "$base" "parallel must be true or false, got '$parallel'"
  fi

  # A task without observable acceptance criteria cannot be verified as done.
  if ! grep -qiE '^#+[[:space:]]*acceptance criteria' "$file"; then
    fail "$base" "no 'Acceptance criteria' heading in the body"
  fi

  depends_of["$id"]="$depends"
  parallel_of["$id"]="$parallel"
  conflicts_of["$id"]="$conflicts"
  epic_of["$id"]="$epic"
  [[ -z "$epic" ]] || epic_count["$epic"]=$(( ${epic_count[$epic]:-0} + 1 ))
done

# Pass 2: cross-references.
for id in "${!seen_id[@]}"; do
  for dep in ${depends_of[$id]:-}; do
    [[ -n "${seen_id[$dep]:-}" ]] || fail "$id" "depends_on references an unknown task: '$dep'"
    [[ "$dep" != "$id" ]] || fail "$id" "depends_on lists itself"
  done
  for other in ${conflicts_of[$id]:-}; do
    [[ -n "${seen_id[$other]:-}" ]] || fail "$id" "conflicts_with references an unknown task: '$other'"
    [[ "$other" != "$id" ]] || fail "$id" "conflicts_with lists itself"
  done
done

# Pass 3: dependency cycles, by repeatedly removing tasks whose dependencies
# are all resolved. Whatever remains is part of a cycle.
declare -A unresolved=()
for id in "${!seen_id[@]}"; do unresolved["$id"]=1; done

progress=1
while ((progress == 1)); do
  progress=0
  for id in "${!unresolved[@]}"; do
    ready=1
    for dep in ${depends_of[$id]:-}; do
      [[ -n "${seen_id[$dep]:-}" ]] || continue
      [[ -z "${unresolved[$dep]:-}" ]] || { ready=0; break; }
    done
    if ((ready == 1)); then
      unset 'unresolved[$id]'
      progress=1
    fi
  done
done

if ((${#unresolved[@]} > 0)); then
  cycle="$(printf '%s ' "${!unresolved[@]}")"
  fail "${cycle% }" "dependency cycle: these tasks can never become ready"
fi

# Pass 4: epic size. An epic past the cap is a decomposition that was not
# finished, and it makes the dependency graph hard to reason about.
for epic in "${!epic_count[@]}"; do
  if ((epic_count[$epic] > max_per_epic)); then
    fail "$epic" "epic holds ${epic_count[$epic]} tasks, more than the $max_per_epic allowed"
  fi
done

# Pass 5: the decomposition summary. Decomposition also produces the grouping,
# the serialization points and the critical path, and those are reasoning, not
# something derivable from the task files. Without a file they die with the
# session that produced them and the approval gate has nothing to read.
summary_name="$(basename "$decomposition")"
if [[ ! -f "$decomposition" ]]; then
  fail "$summary_name" "no decomposition summary at $decomposition"
else
  declare -A declared_epic_of=()
  while IFS=$'\t' read -r declared_epic declared_id; do
    [[ -n "$declared_id" ]] || continue
    declared_epic_of["$declared_id"]="$declared_epic"
  done < <(summary_rows "$decomposition")

  # Both directions matter. A task in the summary with no file is a lane that
  # can never start; a task file absent from the summary is work nobody
  # approved, which a launcher would happily run anyway.
  for declared_id in "${!declared_epic_of[@]}"; do
    if [[ -z "${seen_id[$declared_id]:-}" ]]; then
      fail "$summary_name" "lists a task with no file: '$declared_id'"
    elif [[ "${declared_epic_of[$declared_id]}" != "${epic_of[$declared_id]}" ]]; then
      fail "$declared_id" "epic is '${epic_of[$declared_id]}' in the task file, '${declared_epic_of[$declared_id]}' in $summary_name"
    fi
  done

  for id in "${!seen_id[@]}"; do
    [[ -n "${declared_epic_of[$id]:-}" ]] || fail "$id" "missing from $summary_name"
  done

  # The launcher reads the fields, not the summary, so the two must agree: a set
  # the summary calls serial runs one lane at a time only if every task says so.
  run_as="$(grep -m1 '^\*\*Run as:\*\*' "$decomposition" || true)"
  alone=0
  for id in "${!seen_id[@]}"; do
    [[ "${parallel_of[$id]}" != false ]] || alone=$((alone + 1))
  done
  case "$run_as" in
    *'|'*) fail "$summary_name" "Run as still reads 'lanes | serially': pick one" ;;
    *serial*)
      for id in "${!seen_id[@]}"; do
        [[ "${parallel_of[$id]}" == false ]] ||
          fail "$id" "$summary_name runs the set serially, so parallel must be false"
      done
      ;;
    *lanes*)
      if ((${#seen_id[@]} > 1 && alone == ${#seen_id[@]})); then
        fail "$summary_name" "every task runs alone, so Run as should say serially"
      fi
      ;;
    *) fail "$summary_name" "no 'Run as:' line saying lanes or serially" ;;
  esac
fi

printf 'TASKS\t%s\n' "${#seen_id[@]}"
printf 'EPICS\t%s\n' "${#epic_count[@]}"

if ((failures > 0)); then
  printf 'RESULT\tinvalid\n'
  printf 'FAILURES\t%s\n' "$failures"
  exit 2
fi

printf 'RESULT\tvalid\n'
