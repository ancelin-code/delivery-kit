#!/usr/bin/env bash
set -euo pipefail

# Keep a task set moving without anyone polling: watch the remote, report what
# changed, and launch the tasks each merge makes ready.
#
# Advancing a task set is deterministic once decomposition is approved: a merge
# makes tasks ready, and a ready task gets a lane. Only merging needs a human.
# This loop does the rest and prints one line per event, so an agent running it
# in the background is told what happened instead of asking.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: bash follow.sh [options] [-- launcher options]

Run from the repository root. Polls task state, prints events, and launches
tasks as they become ready. Options after -- go to launch-lanes.sh, for example
-- --effort high --no-web.

Options:
  --interval <s>         Seconds between polls (default: 30).
  --summary-every <s>    Seconds between WAITING summaries (default: 300).
  --max-lanes <n>        Lanes running at once on this machine (default: 3).
  --no-launch            Report only; never start a lane.
  --max-polls <n>        Stop after n polls (default: no limit).
  --log-dir <dir>        Lane logs (default: .lanes/logs).
  --status-script <path> status.sh from fourmee-status (default: beside this skill).
  --launcher <path>      launch-lanes.sh (default: beside this script).
  -h, --help             Print this help.

Events, tab-separated, one per line:
  LAUNCHED     <id> ...            a lane started, as the launcher prints it
  PUBLISHED    <id> <url>          a lane opened its draft pull request
  LANE-FAILED  <id> <last line>    a lane ended without a pull request
  IN-REVIEW    <id>                a pull request left draft
  MERGED       <id>                a task is done
  WAITING      review=<ids> running=<id:minutes ...>
  COMPLETE                         every task is merged
  STUCK        <ids>               blocked, with nothing in flight to unblock them
  ERROR        <message>           task state could not be read; retried

Exit codes:
  0  every task is merged, or --max-polls was reached
  1  usage error, or task state unreadable five polls in a row
  3  stuck: the remaining tasks can never become ready
USAGE
}

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
interval=30
summary_every=300
max_lanes=3
launch=1
max_polls=0
log_dir=".lanes/logs"
status_script="$here/../../fourmee-status/scripts/status.sh"
launcher="$here/launch-lanes.sh"
launcher_args=()

while (($# > 0)); do
  case "$1" in
    --interval) [[ $# -ge 2 ]] || die "--interval requires a value"; interval="$2"; shift 2 ;;
    --summary-every) [[ $# -ge 2 ]] || die "--summary-every requires a value"; summary_every="$2"; shift 2 ;;
    --max-lanes) [[ $# -ge 2 ]] || die "--max-lanes requires a value"; max_lanes="$2"; shift 2 ;;
    --no-launch) launch=0; shift ;;
    --max-polls) [[ $# -ge 2 ]] || die "--max-polls requires a value"; max_polls="$2"; shift 2 ;;
    --log-dir) [[ $# -ge 2 ]] || die "--log-dir requires a value"; log_dir="$2"; shift 2 ;;
    --status-script) [[ $# -ge 2 ]] || die "--status-script requires a value"; status_script="$2"; shift 2 ;;
    --launcher) [[ $# -ge 2 ]] || die "--launcher requires a value"; launcher="$2"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    --) shift; launcher_args=("$@"); break ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ "$interval" =~ ^[0-9]+$ ]] || die "--interval must be a number of seconds"
[[ "$max_lanes" =~ ^[1-9][0-9]*$ ]] || die "--max-lanes must be a positive number"
[[ -f "$status_script" ]] || die "status script not found: $status_script"
((launch == 0)) || [[ -f "$launcher" ]] || die "launcher not found: $launcher"

event() {
  local IFS=$'\t'
  printf '%s\n' "$*"
}

conflicts_of() {
  local file="delivery/tasks/$1.md"
  [[ -f "$file" ]] || return 0
  awk '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    /^conflicts_with:/ { sub(/^conflicts_with:[ \t]*/, ""); gsub(/[][,]/, " "); print; exit }
  ' "$file"
}

# A lane's log ends with what its last step printed: the publisher's PUBLISHED
# or NOTHING, the release's RELEASED or KEPT, or an ERROR from either.
lane_end() {
  local log="$log_dir/$1.log"
  [[ -f "$log" ]] || return 0
  grep -E $'^(PUBLISHED|NOTHING|RELEASED|KEPT|ERROR)\t' "$log" | tail -n 1 || true
}

declare -A state=() started=() reported=() published=() skipped=()
polls=0
failures=0
last_summary=$(date +%s)

while :; do
  polls=$((polls + 1))
  if ! rows="$(bash "$status_script" 2>/dev/null)"; then
    failures=$((failures + 1))
    event ERROR "task state could not be read (attempt $failures)"
    ((failures < 5)) || exit 1
  else
    failures=0
    declare -A now=()
    ready=() in_flight=() blocked=() review=() running=()
    while IFS=$'\t' read -r kind id st _; do
      [[ "$kind" == TASK ]] || continue
      now["$id"]="$st"
      case "$st" in
        ready) ready+=("$id") ;;
        in-progress | in-review) in_flight+=("$id") ;;
        blocked) blocked+=("$id") ;;
      esac
    done <<<"$rows"

    for id in "${!now[@]}"; do
      before="${state[$id]:-}"
      after="${now[$id]}"
      [[ "$before" == "$after" ]] && continue
      [[ "$after" == "done" && -n "$before" ]] && event MERGED "$id"
      [[ "$after" == in-review && -n "$before" ]] && event IN-REVIEW "$id"
    done

    # A lane's outcome is in its log, not on the remote: a draft pull request is
    # still "in progress" there, and a failed lane may have left nothing at all.
    # A local log with no outcome yet is a lane running on this machine, whoever
    # launched it, and it counts against this machine's lanes.
    for id in "${in_flight[@]+"${in_flight[@]}"}" "${!started[@]}"; do
      [[ -z "${reported[$id]:-}" && -f "$log_dir/$id.log" ]] || continue
      end="$(lane_end "$id")"
      if [[ -z "$end" ]]; then
        [[ " ${running[*]} " == *" $id "* ]] || running+=("$id")
        [[ -n "${started[$id]:-}" ]] || started["$id"]=$(date +%s)
        continue
      fi
      reported["$id"]=1
      IFS=$'\t' read -r what _ url <<<"$end"
      if [[ "$what" == PUBLISHED ]]; then
        published["$id"]=1
        event PUBLISHED "$id" "$url"
      else
        event LANE-FAILED "$id" "$end"
      fi
    done
    for id in "${in_flight[@]+"${in_flight[@]}"}"; do
      [[ "${now[$id]}" == in-review || -n "${published[$id]:-}" ]] && review+=("$id")
    done

    # Launch what this machine has room for. The launcher checks conflicts only
    # within its own batch, so skip here what conflicts with work in flight.
    if ((launch == 1)) && ((${#ready[@]} > 0)); then
      slots=$((max_lanes - ${#running[@]}))
      candidates=()
      for id in "${ready[@]}"; do
        clash=""
        for other in "${in_flight[@]+"${in_flight[@]}"}"; do
          for c in $(conflicts_of "$id"); do [[ "$c" == "$other" ]] && clash="$other"; done
          for c in $(conflicts_of "$other"); do [[ "$c" == "$id" ]] && clash="$other"; done
        done
        if [[ -n "$clash" ]]; then
          [[ -n "${skipped[$id]:-}" ]] || event SKIP "$id" "conflicts with $clash, in flight"
          skipped["$id"]=1
        else
          candidates+=("$id")
        fi
      done
      if ((slots > 0 && ${#candidates[@]} > 0)); then
        while IFS= read -r line; do
          case "$line" in
            LAUNCHED*)
              event "$line"
              id="$(cut -f2 <<<"$line")"
              started["$id"]=$(date +%s)
              running+=("$id")
              ;;
            ERROR*)
              [[ -n "${skipped[$line]:-}" ]] || event "$line"
              skipped["$line"]=1
              ;;
            SKIP*)
              key="$(cut -f2- <<<"$line")"
              [[ -n "${skipped[$key]:-}" ]] || event "$line"
              skipped["$key"]=1
              ;;
          esac
        done < <(printf '%s\n' "${candidates[@]}" |
          bash "$launcher" --max-lanes "$slots" "${launcher_args[@]+"${launcher_args[@]}"}" 2>&1 || true)
      fi
    fi

    state=()
    for id in "${!now[@]}"; do state["$id"]="${now[$id]}"; done

    if ((${#ready[@]} + ${#in_flight[@]} + ${#blocked[@]} == 0)) && ((${#now[@]} > 0)); then
      event COMPLETE
      exit 0
    fi
    if ((${#ready[@]} + ${#in_flight[@]} == 0 && ${#blocked[@]} > 0)); then
      event STUCK "${blocked[*]}"
      exit 3
    fi

    if (($(date +%s) - last_summary >= summary_every)); then
      last_summary=$(date +%s)
      lanes=()
      for id in "${running[@]+"${running[@]}"}"; do
        lanes+=("$id:$((($(date +%s) - started[$id]) / 60))m")
      done
      event WAITING "review=${review[*]:--}" "running=${lanes[*]:--}"
    fi
  fi

  ((max_polls == 0 || polls < max_polls)) || exit 0
  sleep "$interval"
done
