#!/usr/bin/env bash
set -euo pipefail

# Where the project stands and what comes next, in one call.
#
# Everything is read from delivery/ and git, the same sources a phase starts
# from, so the answer never depends on a conversation having been kept alive.
# The next action is derived here rather than reasoned out by the agent: the
# rules are fixed, and applying them by hand costs a dozen tool calls.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: bash where.sh [--remote <name>] [--no-fetch]

Run from the repository root. Prints, tab-separated:

  ROUTING  present | missing          the AGENTS.md block that routes requests here
  PHASE    <phase> <state> <path>     requirements, design, decomposition
  TASK     ...                        one row per task, as fourmee-status prints it
  SUMMARY  ...                        task counts, as fourmee-status prints it
  REVIEW   <id> <pr> <lens> <skill> <why>
                                      per task in review, one row per lens; skill
                                      is - when no skill is mapped to the lens
  NEXT     <action> <detail>          what to do now; more than one when both apply

Options:
  --remote <name>   Shared remote, when it is not origin.
  --no-fetch        Read cached refs instead of fetching.
  -h, --help        Print this help.

Exit codes:
  0  the position was read
  1  usage or environment error, including task state that cannot be read
USAGE
}

status_args=()
while (($# > 0)); do
  case "$1" in
    --remote) [[ $# -ge 2 ]] || die "--remote requires a value"; status_args+=("$1" "$2"); shift 2 ;;
    --no-fetch) status_args+=("$1"); shift ;;
    -h | --help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"
[[ "$(git rev-parse --show-toplevel)" == "$(pwd -P)" ]] || die "run from the repository root"

# The kit installs as a whole, so fourmee-status sits beside this skill, the
# same assumption launch-lanes.sh makes for claim.sh.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
status_script="$here/../../fourmee-status/scripts/status.sh"
[[ -f "$status_script" ]] || die "fourmee-status is not installed beside fourmee"

# The value of the "**Status:**" line, lowercased; empty when there is none.
# An unfilled template reads "draft | approved", which is not approved.
status_of() {
  awk '
    /^\*\*Status:\*\*/ {
      sub(/^\*\*Status:\*\*[ \t]*/, "")
      sub(/[ \t]+$/, "")
      print tolower($0)
      exit
    }
  ' "$1"
}

if grep -qs 'fourmee:routing' AGENTS.md; then
  printf 'ROUTING\tpresent\n'
  routing=present
else
  printf 'ROUTING\tmissing\n'
  routing=missing
fi

prd="delivery/prd.md"
if [[ ! -f "$prd" ]]; then
  prd_state=missing
elif [[ "$(status_of "$prd")" == approved ]]; then
  prd_state=approved
else
  prd_state=draft
fi
printf 'PHASE\trequirements\t%s\t%s\n' "$prd_state" "$prd"

# The spine is optional: a use case whose parts need no agreed interface has
# none. It is pending while any contract is not agreed or any record the kit
# may have written is still proposed.
shopt -s nullglob
contracts=(delivery/contracts/*.md)
records=(delivery/decisions/*.md docs/adr/*.md docs/decisions/*.md)
shopt -u nullglob
pending=()
for file in "${contracts[@]}"; do
  [[ "$(status_of "$file")" == agreed ]] || pending+=("$file")
done
for file in "${records[@]}"; do
  [[ "$(status_of "$file")" != proposed ]] || pending+=("$file")
done
if ((${#pending[@]} > 0)); then
  design_state=pending
elif ((${#contracts[@]} > 0)); then
  design_state=approved
else
  design_state=none
fi
printf 'PHASE\tdesign\t%s\t%s\n' "$design_state" "${pending[*]:-delivery/contracts/}"

decomposition="delivery/decomposition.md"
if [[ ! -f "$decomposition" ]]; then
  decomposition_state=missing
elif [[ "$(status_of "$decomposition")" == approved ]]; then
  decomposition_state=approved
else
  decomposition_state=draft
fi
printf 'PHASE\tdecomposition\t%s\t%s\n' "$decomposition_state" "$decomposition"

# Scripts are named by a path runnable from the repository root, so an agent can
# act on a NEXT line without looking for them.
shown="$(realpath --relative-to=. "$here" 2>/dev/null || printf '%s' "$here")"

next() {
  printf 'NEXT\t%s\t%s\n' "$1" "$2"
}

[[ "$routing" == present ]] ||
  next install-routing "route this project's requests to the kit: bash $shown/install-routing.sh"

if [[ "$prd_state" == missing ]]; then
  next write-requirements "no delivery/prd.md: write it with fourmee-spec, stage A"
  exit 0
fi
if [[ "$prd_state" == draft ]]; then
  next approve-requirements "delivery/prd.md awaits human approval"
  exit 0
fi
if [[ "$design_state" == pending ]]; then
  next approve-design "awaiting approval: ${pending[*]}"
  exit 0
fi
if [[ "$decomposition_state" == missing ]]; then
  if [[ "$design_state" == none ]]; then
    next design-or-decompose "record the spine with fourmee-spec, stage B, if parts need an agreed interface; otherwise decompose with fourmee-decompose"
  else
    next decompose "decompose the approved requirements with fourmee-decompose"
  fi
  exit 0
fi
if [[ "$decomposition_state" == draft ]]; then
  next approve-decomposition "delivery/decomposition.md and delivery/tasks/ await human approval"
  exit 0
fi

# Lanes. Task state is fourmee-status's to derive; it fails loudly when pull
# request state cannot be read, and so does this.
rows="$(bash "$status_script" "${status_args[@]+"${status_args[@]}"}")" ||
  die "task state could not be read; see the error above"
printf '%s\n' "$rows"

ids_in() {
  printf '%s\n' "$rows" | awk -F'\t' -v s="$1" '$1 == "TASK" && $3 == s { printf "%s%s", sep, $2; sep = " " }'
}
ready="$(ids_in ready)"
in_progress="$(ids_in in-progress)"
in_review="$(ids_in in-review)"
blocked="$(ids_in blocked)"
in_flight="${in_progress}${in_progress:+${in_review:+ }}${in_review}"

# Which reviewer each pull request in review should get. A lens is a concern
# worth a dedicated review; the project's lens file maps it to the skill that
# reviews it and to the paths that bring it in. "general" applies to every pull
# request. A lens also comes from the task's review field, set at decomposition,
# and from a review:<lens> label a person adds to the pull request.
lenses_file="delivery/review-lenses.conf"
declare -A skill_of=() patterns_of=() why=()
lens_order=()
if [[ -f "$lenses_file" ]]; then
  # read -a splits without globbing, so a pattern is kept as written.
  while read -r -a words; do
    ((${#words[@]} > 0)) || continue
    [[ "${words[0]}" != \#* ]] || continue
    lens_order+=("${words[0]}")
    skill_of["${words[0]}"]="${words[1]:--}"
    patterns_of["${words[0]}"]="${words[*]:2}"
  done <"$lenses_file"
fi

task_lenses() {
  awk '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    /^review:/ { sub(/^review:[ \t]*/, ""); gsub(/[][,]/, " "); print; exit }
  ' "delivery/tasks/$1.md" 2>/dev/null || true
}

# The clone a task lands in: a sibling named by its repo field, else this one.
# Its pull request lives there, and in a set spanning repositories its number is
# only meaningful with the repository's name in front.
task_repo() {
  awk '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    /^repo:/ { sub(/^repo:[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit }
  ' "delivery/tasks/$1.md" 2>/dev/null || true
}

add_lens() {
  [[ -n "${why[$1]:-}" ]] || order+=("$1")
  [[ ",${why[$1]:-}," == *",$2,"* ]] || why["$1"]="${why[$1]:+${why[$1]},}$2"
}

for id in $in_review; do
  repo="$(task_repo "$id")"
  pr="$(cd "${repo:+../}${repo:-.}" && gh pr view "task/$id" --json number,labels,files --jq \
    '"N\t\(.number)", (.labels[].name | "L\t\(.)"), (.files[].path | "F\t\(.)")' 2>/dev/null)" ||
    die "gh could not read the pull request for task/$id${repo:+ in $repo}"
  number="$(printf '%s\n' "$pr" | awk -F'\t' '$1 == "N" { print $2; exit }')"
  mapfile -t files < <(printf '%s\n' "$pr" | awk -F'\t' '$1 == "F" { print $2 }')

  why=()
  order=()
  add_lens general default
  read -r -a declared <<<"$(task_lenses "$id")"
  for lens in "${declared[@]+"${declared[@]}"}"; do
    add_lens "$lens" task
  done
  while IFS= read -r label; do
    [[ "$label" != review:* ]] || add_lens "${label#review:}" label
  done < <(printf '%s\n' "$pr" | awk -F'\t' '$1 == "L" { print $2 }')
  for lens in "${lens_order[@]+"${lens_order[@]}"}"; do
    matched=""
    read -r -a patterns <<<"${patterns_of[$lens]:-}"
    for pattern in "${patterns[@]+"${patterns[@]}"}"; do
      for file in "${files[@]+"${files[@]}"}"; do
        # shellcheck disable=SC2053 # the pattern is meant to match, not compare
        [[ "$file" == $pattern ]] && { matched="$file"; break 2; }
      done
    done
    [[ -z "$matched" ]] || add_lens "$lens" "path:$matched"
  done

  for lens in "${order[@]}"; do
    printf 'REVIEW\t%s\t%s#%s\t%s\t%s\t%s\n' "$id" "$repo" "$number" "$lens" "${skill_of[$lens]:--}" "${why[$lens]}"
  done
done

[[ -z "$in_review" ]] || next review "pull requests await review, one pass per REVIEW row: $in_review"

# A task with "parallel: false" runs alone: nothing else of the set in flight
# while it runs. A set that serializes is one where every task says so.
runs_alone() {
  [[ "$(awk '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    /^parallel:/ { sub(/^parallel:[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit }
  ' "delivery/tasks/$1.md" 2>/dev/null)" == false ]]
}

if [[ -z "$ready$in_flight$blocked" ]]; then
  next complete "every task is merged; new work starts by revising delivery/prd.md"
elif [[ -n "$ready" ]]; then
  alone_in_flight="" shared="" alone=""
  for id in $in_flight; do ! runs_alone "$id" || alone_in_flight="$id"; done
  for id in $ready; do
    if runs_alone "$id"; then alone+="${alone:+ }$id"; else shared+="${shared:+ }$id"; fi
  done
  if [[ -n "$alone_in_flight" ]]; then
    next wait "$alone_in_flight runs alone and is in flight; then $ready"
  elif [[ -n "$shared" ]]; then
    next start "launch lanes for: $shared (bash $shown/launch-lanes.sh)${alone:+; after they merge, alone: $alone}"
  elif [[ -n "$in_flight" ]]; then
    next wait "$alone runs alone, after in-flight work merges: $in_flight"
  else
    next start "alone, first of: $alone (bash $shown/launch-lanes.sh ${alone%% *})"
  fi
elif [[ -n "$in_flight" ]]; then
  next wait "nothing is ready until in-flight work merges: $in_flight"
else
  next unblock "blocked with nothing in flight, so a dependency will never merge: $blocked"
fi
