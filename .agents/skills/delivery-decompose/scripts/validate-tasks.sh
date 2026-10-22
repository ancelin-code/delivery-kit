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
usage: sh validate-tasks.sh [--tasks-dir <dir>] [--decomposition <path>]

Validates every task file in <dir> (default: delivery/tasks), and the
decomposition summary that has to agree with it. When tasks name the
requirements they cover, or the summary has a Milestones section, also checks
them against the requirements beside it (delivery/prd.md) and the milestone
review notes (delivery/milestones/<slug>.md).

Options:
  --tasks-dir <dir>     Directory holding <id>.md task files (default: delivery/tasks).
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
decomposition=""

while [ $# -gt 0 ]; do
  case "$1" in
    --tasks-dir)
      [ $# -ge 2 ] || die "--tasks-dir requires a value"
      tasks_dir="$2"; shift 2 ;;
    --decomposition)
      [ $# -ge 2 ] || die "--decomposition requires a value"
      decomposition="$2"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    --) shift; break ;;
    -*) die "unknown option: $1" ;;
    *) die "unexpected argument: $1" ;;
  esac
done

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

# The Covers section of a task: one line per requirement, "full<TAB><id>" for
# "- <id>", "part<TAB><id><TAB><note>" for "- <id> (part): <note>", whose note
# may wrap onto indented lines, and "bad<TAB><line>" for anything else.
covers_of() {
  awk '
    function flush() { if (how != "") printf "%s\t%s\t%s\n", how, req, note; how = "" }
    /^##[[:space:]]/ { flush(); in_covers = ($0 ~ /^##[[:space:]]+Covers[[:space:]]*$/); next }
    !in_covers { next }
    /^[-*][ \t]+/ {
      flush()
      line = $0; sub(/^[-*][ \t]+/, "", line); sub(/[ \t]+$/, "", line)
      req = line; sub(/[ \t].*/, "", req); note = ""
      if (req !~ /^[A-Za-z0-9][A-Za-z0-9-]*$/) { how = "bad"; req = line }
      else if (line == req) how = "full"
      else if (line ~ /^[^ \t]+[ \t]+\(part\):/) { how = "part"; note = line; sub(/^[^:]*:[ \t]*/, "", note) }
      else { how = "bad"; req = line }
      next
    }
    /^[ \t]+[^ \t]/ && how == "part" { l = $0; gsub(/^[ \t]+|[ \t]+$/, "", l); note = note (note == "" ? "" : " ") l; next }
    { flush() }
    END { flush() }
  ' "$1"
}

# The facts pass 1 collects, one task per line, for the cross-checks in pass 2:
# "<id><TAB><epic><TAB><parallel><TAB><depends_on><TAB><conflicts_with><TAB><covers>".
store="$(mktemp -d)"
trap 'rm -rf "$store"' EXIT
tab="$(printf '\t')"
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
    -* | *- | *[!-[:lower:][:digit:]]*) fail "$base" "id is not a lowercase slug: '$id'" ;;
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
      . | .. | *[!-._[:alnum:]]*)
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

  # What the task covers of the requirements. A partial cover says what it
  # does, or nobody can tell what is left of the requirement.
  covers=""
  while IFS="$tab" read -r how req note; do
    case "$how" in
      full) covers="$covers${covers:+ }$req" ;;
      part)
        covers="$covers${covers:+ }$req"
        [ -n "$note" ] || fail "$base" "covers $req in part with no note: write '- $req (part): <what this task does of it>'"
        ;;
      bad) fail "$base" "unreadable Covers line '$req': write '- <id>' or '- <id> (part): <note>'" ;;
    esac
  done <<EOF_COVERS
$(covers_of "$file")
EOF_COVERS

  # A task without observable acceptance criteria cannot be verified as done.
  if ! grep -qiE '^#+[[:space:]]*acceptance criteria' "$file"; then
    fail "$base" "no 'Acceptance criteria' heading in the body"
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$id" "$epic" "$parallel" "$depends" "$conflicts" "$covers" >>"$store/facts"
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

# The milestone plan, one line per milestone in plan order:
# "<slug><TAB><has exit><TAB><epics><TAB><targets><TAB><review status>".
# A target's "(part)" is dropped: which part is the tasks' to say.
: >"$store/milestones"
has_milestones=0
if [ -f "$decomposition" ] && grep -Eq '^##[[:space:]]+Milestones[[:space:]]*$' "$decomposition"; then
  has_milestones=1
  awk '
    # An empty list is written "-": read splits on tabs as whitespace, and would
    # otherwise shift the fields after it.
    function flush() { if (slug != "") printf "%s\t%s\t%s\t%s\n", slug, has_exit, (epics == "" ? "-" : epics), (targets == "" ? "-" : targets) }
    function ids(s) {
      sub(/^\*\*[A-Za-z]+:\*\*/, "", s); gsub(/\([^)]*\)/, " ", s); gsub(/,/, " ", s)
      gsub(/[ \t]+/, " ", s); sub(/^ /, "", s); sub(/ $/, "", s); return s
    }
    /^##[[:space:]]/ { flush(); slug = ""; in_plan = ($0 ~ /^##[[:space:]]+Milestones[[:space:]]*$/); next }
    !in_plan { next }
    /^###[[:space:]]/ {
      flush(); slug = $0; sub(/^###[[:space:]]+/, "", slug); sub(/[[:space:]]+$/, "", slug)
      has_exit = 0; epics = ""; targets = ""; open = ""; next
    }
    slug == "" { next }
    /^\*\*Exit:\*\*[ \t]*[^ \t]/ { has_exit = 1; open = ""; next }
    /^\*\*Epics:\*\*/ { epics = ids($0); open = "epics"; next }
    /^\*\*Requirements:\*\*/ { targets = ids($0); open = "targets"; next }
    /^[ \t]*$/ || /^\*\*/ { open = ""; next }
    open == "epics" { epics = ids(epics " " $0) }
    open == "targets" { targets = ids(targets " " $0) }
    END { flush() }
  ' "$decomposition" | while IFS="$tab" read -r slug has_exit epics targets; do
    [ "$epics" != - ] || epics=""
    [ "$targets" != - ] || targets=""
    review=""
    note="$(dirname "$decomposition")/milestones/$slug.md"
    if [ -f "$note" ]; then
      review="$(awk '/^\*\*Status:\*\*/ { sub(/^\*\*Status:\*\*[ \t]*/, ""); sub(/[ \t]+$/, ""); print tolower($0); exit }' "$note")"
    fi
    printf '%s\t%s\t%s\t%s\t%s\n' "$slug" "$has_exit" "$epics" "$targets" "$review"
  done >"$store/milestones"
fi

# Requirement ids, from the outcomes of the requirements beside the summary:
# lines reading "- **<id>.** ...". Only read when something refers to them.
prd="$(dirname "$decomposition")/prd.md"
: >"$store/requirements"
has_prd=0
if [ -f "$prd" ]; then
  has_prd=1
  awk '
    /^[-*][ \t]+\*\*[A-Za-z0-9][A-Za-z0-9-]*\.\*\*/ {
      id = $0; sub(/^[-*][ \t]+\*\*/, "", id); sub(/\.\*\*.*/, "", id); print id
    }
  ' "$prd" >"$store/requirements"
fi

# Passes 2 to 4 compare tasks with each other, which is what awk is for.
#
# Pass 2: cross-references.
# Pass 3: dependency cycles, by repeatedly resolving tasks whose dependencies
#         are all resolved. Whatever stays unresolved is part of a cycle.
# Pass 4: the decomposition summary. Decomposition also produces the grouping,
#         the serialization points and the critical path, and those are
#         reasoning, not something derivable from the task files. Without a
#         file they die with the session that produced them and the approval
#         gate has nothing to read.
checks="$(RUN_AS="$run_as" SUMMARY="$summary_name" SUMMARY_PATH="$decomposition" HAS_SUMMARY="$has_summary" \
  HAS_MILESTONES="$has_milestones" HAS_PRD="$has_prd" PRD="$prd" \
  awk -F'\t' -v facts="$store/facts" -v plan="$store/milestones" -v reqs="$store/requirements" '
  function fail(who, why) { printf "FAIL\t%s\t%s\n", who, why }
  FILENAME == facts {
    # one line per task file
    if (!($1 in seen)) { ids[++n] = $1; seen[$1] = 1 }
    epic_of[$1] = $2; parallel_of[$1] = $3; depends_of[$1] = $4; conflicts_of[$1] = $5; covers_of[$1] = $6
    if ($2 != "") {
      if (!($2 in epic_count)) { epics[++e] = $2 }
      epic_count[$2]++
    }
    next
  }
  FILENAME == plan {
    # one line per milestone, in plan order
    m++; slug_at[m] = $1; exit_at[m] = $2; epics_at[m] = $3; targets_at[m] = $4; review_at[m] = $5
    next
  }
  FILENAME == reqs { requirement[$1] = 1; requirements++; next }
  { declared_ids[++d] = $2; declared_epic[$2] = $1; declared_epics[$1] = 1 }
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

    # Covers name requirement ids that the requirements document defines.
    prd = ENVIRON["PRD"]
    for (i = 1; i <= n; i++) {
      id = ids[i]
      k = split(covers_of[id], cov, " ")
      for (j = 1; j <= k; j++) {
        if (ENVIRON["HAS_PRD"] != 1) fail(id, "covers \047" cov[j] "\047, but there is no " prd)
        else if (!requirements) fail(id, "covers \047" cov[j] "\047, but " prd " has no ids: an outcome reads \047- **<id>.** ...\047")
        else if (!(cov[j] in requirement)) fail(id, "covers \047" cov[j] "\047, which is no requirement id in " prd)
      }
    }

    # Milestones. The current one is the first whose review note is not
    # approved: only it and the closed ones before it may have tasks, so the
    # next is cut after a person has looked at what this one taught.
    current = 0; scope = 0
    if (ENVIRON["HAS_MILESTONES"] == 1) {
      if (m == 0) fail(ENVIRON["SUMMARY"], "has a Milestones section with no \047### <slug>\047 milestone in it")
      for (i = 1; i <= m; i++) {
        s = slug_at[i]
        if (s !~ /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/) fail(s, "milestone is not a lowercase slug")
        if (s in milestone_index) fail(s, "milestone is listed twice")
        milestone_index[s] = i
        if (exit_at[i] != 1) fail(s, "milestone has no \047**Exit:**\047 line stating its observable outcome")
        k = split(epics_at[i], es, " ")
        for (j = 1; j <= k; j++) {
          if (es[j] in milestone_of_epic) fail(es[j], "epic is in two milestones: " milestone_of_epic[es[j]] " and " s)
          else milestone_of_epic[es[j]] = s
          if (!(es[j] in declared_epics) && !(es[j] in epic_count)) fail(s, "lists epic \047" es[j] "\047, which has no section under Epics and no task")
        }
        k = split(targets_at[i], ts, " ")
        for (j = 1; j <= k; j++) {
          if (ENVIRON["HAS_PRD"] != 1) fail(s, "targets \047" ts[j] "\047, but there is no " prd)
          else if (!(ts[j] in requirement)) fail(s, "targets \047" ts[j] "\047, which is no requirement id in " prd)
        }
        if (!current && review_at[i] != "approved") current = i
        if (epics_at[i] != "" && (!current || current == i)) scope = i
      }
      for (ep in declared_epics) if (!(ep in milestone_of_epic)) fail(ep, "epic belongs to no milestone: list it on a milestone\047s **Epics:** line")
      for (i = 1; i <= n; i++) {
        id = ids[i]; ep = epic_of[id]
        if (!(ep in milestone_of_epic)) {
          if (!(ep in declared_epics)) fail(id, "epic \047" ep "\047 belongs to no milestone")
          continue
        }
        mi = milestone_index[milestone_of_epic[ep]]
        if (current && mi > current)
          fail(id, "belongs to milestone " slug_at[mi] ", after the current one, " slug_at[current] ": cut it once " slug_at[current] "\047s review note is approved")
        if (mi == scope) in_scope[id] = 1
        k = split(covers_of[id], cov, " ")
        for (j = 1; j <= k; j++) covered_in[mi, cov[j]] = 1
      }
      if (current && epics_at[current] != "") {
        k = split(targets_at[current], ts, " ")
        for (j = 1; j <= k; j++)
          if (!((current, ts[j]) in covered_in))
            fail(slug_at[current], "targets " ts[j] ", but no task of the milestone covers it")
      }
    } else {
      for (i = 1; i <= n; i++) in_scope[ids[i]] = 1
    }

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
      # With milestones, Run as describes the cut being run: the current
      # milestone tasks, or those of the last one cut once every milestone is closed.
      alone = 0; scoped = 0
      for (i = 1; i <= n; i++) if (ids[i] in in_scope) { scoped++; if (parallel_of[ids[i]] == "false") alone++ }
      run_as = ENVIRON["RUN_AS"]
      if (run_as ~ /\|/) fail(summary, "Run as still reads \047lanes | serially\047: pick one")
      else if (run_as ~ /serial/) {
        for (i = 1; i <= n; i++)
          if ((ids[i] in in_scope) && parallel_of[ids[i]] != "false")
            fail(ids[i], summary " runs the set serially, so parallel must be false")
      } else if (run_as ~ /lanes/) {
        if (scoped > 1 && alone == scoped) fail(summary, "every task runs alone, so Run as should say serially")
      } else fail(summary, "no \047Run as:\047 line saying lanes or serially")
    }
    printf "TASKS\t%s\n", n
    printf "EPICS\t%s\n", e
    if (ENVIRON["HAS_MILESTONES"] == 1) printf "MILESTONES\t%s\tcurrent=%s\n", m, (current ? slug_at[current] : "-")
  }
' "$store/facts" "$store/milestones" "$store/requirements" "$store/declared")"

printf '%s\n' "$checks"
failures=$((failures + $(printf '%s\n' "$checks" | grep -c '^FAIL' || true)))

if [ "$failures" -gt 0 ]; then
  printf 'RESULT\tinvalid\n'
  printf 'FAILURES\t%s\n' "$failures"
  exit 2
fi

printf 'RESULT\tvalid\n'
