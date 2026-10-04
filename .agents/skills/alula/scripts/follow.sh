#!/bin/sh
set -eu

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
usage: sh follow.sh [options] [-- launcher options]

Run from the repository root. Polls task state, prints events, and launches
tasks as they become ready. Options after -- go to launch-lanes.sh, for example
-- --no-web.

Options:
  --interval <s>         Seconds between polls (default: 30).
  --summary-every <s>    Seconds between WAITING summaries (default: 300).
  --max-lanes <n>        Lanes running at once on this machine (default: 3).
  --no-launch            Report only; never start a lane.
  --max-polls <n>        Stop after n polls (default: no limit).
  --log-dir <dir>        Lane logs (default: .lanes/logs).
  --status-script <path> status.sh from alula-status (default: beside this skill).
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

here="$(cd "$(dirname "$0")" && pwd)"
interval=30
summary_every=300
max_lanes=3
launch=1
max_polls=0
log_dir=".lanes/logs"
status_script="$here/../../alula-status/scripts/status.sh"
launcher="$here/launch-lanes.sh"

while [ $# -gt 0 ]; do
  case "$1" in
    --interval) [ $# -ge 2 ] || die "--interval requires a value"; interval="$2"; shift 2 ;;
    --summary-every) [ $# -ge 2 ] || die "--summary-every requires a value"; summary_every="$2"; shift 2 ;;
    --max-lanes) [ $# -ge 2 ] || die "--max-lanes requires a value"; max_lanes="$2"; shift 2 ;;
    --no-launch) launch=0; shift ;;
    --max-polls) [ $# -ge 2 ] || die "--max-polls requires a value"; max_polls="$2"; shift 2 ;;
    --log-dir) [ $# -ge 2 ] || die "--log-dir requires a value"; log_dir="$2"; shift 2 ;;
    --status-script) [ $# -ge 2 ] || die "--status-script requires a value"; status_script="$2"; shift 2 ;;
    --launcher) [ $# -ge 2 ] || die "--launcher requires a value"; launcher="$2"; shift 2 ;;
    -h | --help) usage; exit 0 ;;
    --) shift; break ;;
    *) die "unknown option: $1" ;;
  esac
done
# What is left in "$@" goes to the launcher.

case "$interval" in "" | *[!0-9]*) die "--interval must be a number of seconds" ;; esac
case "$max_lanes" in "" | 0* | *[!0-9]*) die "--max-lanes must be a positive number" ;; esac
[ -f "$status_script" ] || die "status script not found: $status_script"
[ "$launch" -eq 0 ] || [ -f "$launcher" ] || die "launcher not found: $launcher"

# Everything the loop remembers lives in files, since POSIX sh has no arrays or
# associative arrays. A map is a directory with one file per task id, a list is
# a file with one entry per line, and ids are slugs, so they are safe names.
store="$(mktemp -d)"
trap 'rm -rf "$store"' EXIT
tab="$(printf '\t')"
mkdir "$store/state" "$store/started" "$store/reported" "$store/published"

put() { mkdir -p "$store/$1"; printf '%s' "$3" >"$store/$1/$2"; }
get() { cat "$store/$1/$2" 2>/dev/null || true; }
has() { [ -e "$store/$1/$2" ]; }

add() { printf '%s\n' "$2" >>"$store/$1"; }
in_list() { [ -f "$store/$1" ] && grep -Fxq -- "$2" "$store/$1"; }
count() { if [ -f "$store/$1" ]; then wc -l <"$store/$1" | tr -d ' '; else printf 0; fi; }
words() { if [ -f "$store/$1" ]; then tr '\n' ' ' <"$store/$1" | sed 's/ $//'; fi; }
items() { if [ -f "$store/$1" ]; then cat "$store/$1"; fi; }

started_ids() {
  for path in "$store/started"/*; do
    [ ! -e "$path" ] || printf '%s\n' "${path##*/}"
  done
}

event() (
  IFS="$tab"
  printf '%s\n' "$*"
)

conflicts_of() {
  file="delivery/tasks/$1.md"
  [ -f "$file" ] || return 0
  awk '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    /^conflicts_with:/ { sub(/^conflicts_with:[ \t]*/, ""); gsub(/[][,]/, " "); print; exit }
  ' "$file"
}

# A lane's log ends with what its last step printed: the publisher's PUBLISHED
# or NOTHING, the release's RELEASED or KEPT, or an ERROR from either.
lane_end() {
  [ -f "$log_dir/$1.log" ] || return 0
  grep -E "^(PUBLISHED|NOTHING|RELEASED|KEPT|ERROR)$tab" "$log_dir/$1.log" | tail -n 1 || true
}

polls=0
failures=0
last_summary=$(date +%s)

while :; do
  polls=$((polls + 1))
  if ! rows="$(sh "$status_script" 2>/dev/null)"; then
    failures=$((failures + 1))
    event ERROR "task state could not be read (attempt $failures)"
    [ "$failures" -lt 5 ] || exit 1
  else
    failures=0
    rm -rf "$store/now" "$store/ready" "$store/in_flight" "$store/blocked" "$store/review" "$store/running"
    mkdir "$store/now"
    while IFS="$tab" read -r kind id st _; do
      [ "$kind" = TASK ] || continue
      put now "$id" "$st"
      case "$st" in
        ready) add ready "$id" ;;
        in-progress | in-review) add in_flight "$id" ;;
        blocked) add blocked "$id" ;;
      esac
    done <<EOF_ROWS
$rows
EOF_ROWS

    for path in "$store/now"/*; do
      [ -e "$path" ] || continue
      id="${path##*/}"
      before="$(get state "$id")"
      after="$(get now "$id")"
      [ "$before" != "$after" ] || continue
      [ "$after" != "done" ] || [ -z "$before" ] || event MERGED "$id"
      [ "$after" != in-review ] || [ -z "$before" ] || event IN-REVIEW "$id"
    done

    # A lane's outcome is in its log, not on the remote: a draft pull request is
    # still "in progress" there, and a failed lane may have left nothing at all.
    # A local log with no outcome yet is a lane running on this machine, whoever
    # launched it, and it counts against this machine's lanes.
    for id in $(items in_flight) $(started_ids); do
      ! has reported "$id" && [ -f "$log_dir/$id.log" ] || continue
      end="$(lane_end "$id")"
      if [ -z "$end" ]; then
        in_list running "$id" || add running "$id"
        has started "$id" || put started "$id" "$(date +%s)"
        continue
      fi
      put reported "$id" 1
      IFS="$tab" read -r what _ url <<EOF_END
$end
EOF_END
      if [ "$what" = PUBLISHED ]; then
        put published "$id" 1
        event PUBLISHED "$id" "$url"
      else
        event LANE-FAILED "$id" "$end"
      fi
    done
    for id in $(items in_flight); do
      if [ "$(get now "$id")" = in-review ] || has published "$id"; then add review "$id"; fi
    done

    # Launch what this machine has room for. The launcher checks conflicts only
    # within its own batch, so skip here what conflicts with work in flight.
    if [ "$launch" -eq 1 ] && [ "$(count ready)" -gt 0 ]; then
      slots=$((max_lanes - $(count running)))
      for id in $(items ready); do
        clash=""
        for other in $(items in_flight); do
          for c in $(conflicts_of "$id"); do [ "$c" != "$other" ] || clash="$other"; done
          for c in $(conflicts_of "$other"); do [ "$c" != "$id" ] || clash="$other"; done
        done
        if [ -n "$clash" ]; then
          in_list skipped "$id" || event SKIP "$id" "conflicts with $clash, in flight"
          in_list skipped "$id" || add skipped "$id"
        else
          add candidates "$id"
        fi
      done
      if [ "$slots" -gt 0 ] && [ "$(count candidates)" -gt 0 ]; then
        launched="$(items candidates | sh "$launcher" --max-lanes "$slots" "$@" 2>&1 || true)"
        while IFS= read -r line; do
          case "$line" in
            LAUNCHED*)
              event "$line"
              id="$(printf '%s\n' "$line" | cut -f2)"
              put started "$id" "$(date +%s)"
              add running "$id"
              ;;
            ERROR*)
              in_list skipped "$line" || event "$line"
              in_list skipped "$line" || add skipped "$line"
              ;;
            SKIP*)
              key="$(printf '%s\n' "$line" | cut -f2-)"
              in_list skipped "$key" || event "$line"
              in_list skipped "$key" || add skipped "$key"
              ;;
          esac
        done <<EOF_LAUNCHED
$launched
EOF_LAUNCHED
      fi
      rm -f "$store/candidates"
    fi

    rm -rf "$store/state"
    mv "$store/now" "$store/state"

    if [ $(($(count ready) + $(count in_flight) + $(count blocked))) -eq 0 ] && [ -n "$(ls "$store/state")" ]; then
      event COMPLETE
      exit 0
    fi
    if [ $(($(count ready) + $(count in_flight))) -eq 0 ] && [ "$(count blocked)" -gt 0 ]; then
      event STUCK "$(words blocked)"
      exit 3
    fi

    if [ $(($(date +%s) - last_summary)) -ge "$summary_every" ]; then
      last_summary=$(date +%s)
      lanes=""
      for id in $(items running); do
        lanes="${lanes:+$lanes }$id:$((($(date +%s) - $(get started "$id")) / 60))m"
      done
      review="$(words review)"
      event WAITING "review=${review:--}" "running=${lanes:--}"
    fi
  fi

  [ "$max_polls" -eq 0 ] || [ "$polls" -lt "$max_polls" ] || exit 0
  sleep "$interval"
done
