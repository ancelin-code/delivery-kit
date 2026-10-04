#!/bin/sh
set -eu

# Add the block that routes a project's requests to alula to its
# AGENTS.md, which both Claude Code and Copilot CLI read on every request.
# A skill description only fires when a request happens to match it; this is
# what makes the kit the default for the project rather than one option.
#
# Also seed delivery/review-lenses.conf, so the file that maps review concerns to
# review skills is found where it is read rather than in the conventions.

die() {
  printf 'ERROR\t%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'USAGE'
usage: sh install-routing.sh

Run from the repository root. Appends the routing block to AGENTS.md, creating
the file when there is none, and writes a starter delivery/review-lenses.conf
when the project has none. Running it again changes nothing.

Prints ADDED or PRESENT, then the path, once per file.
USAGE
}

case "${1:-}" in
  "") ;;
  -h | --help) usage; exit 0 ;;
  *) die "unknown option: $1" ;;
esac

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "not inside a git repository"
[ "$(git rev-parse --show-toplevel)" = "$(pwd -P)" ] || die "run from the repository root"

here="$(cd "$(dirname "$0")" && pwd)"
block="$here/../assets/agents-routing.md"
lenses="$here/../assets/review-lenses.conf"
[ -f "$block" ] || die "routing block not found: $block"
[ -f "$lenses" ] || die "review lenses starter not found: $lenses"

if grep -qs 'alula:routing' AGENTS.md; then
  printf 'PRESENT\tAGENTS.md\n'
else
  # Separate the block from existing content by one blank line, whatever the
  # file ended with.
  if [ -s AGENTS.md ]; then
    [ -z "$(tail -c1 AGENTS.md)" ] || printf '\n' >>AGENTS.md
    printf '\n' >>AGENTS.md
  fi
  cat "$block" >>AGENTS.md
  printf 'ADDED\tAGENTS.md\n'
fi

# The project owns this file once it exists, so an edited one is never touched.
target="delivery/review-lenses.conf"
if [ -e "$target" ]; then
  printf 'PRESENT\t%s\n' "$target"
else
  mkdir -p delivery
  cp "$lenses" "$target"
  printf 'ADDED\t%s\n' "$target"
fi
