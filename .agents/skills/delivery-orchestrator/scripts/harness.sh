# shellcheck shell=sh
# Harness adapters, sourced by launch-lanes.sh. Not run on its own.
#
# A harness is the agent CLI that runs a lane's session. Everything the launcher
# knows about one is in this file, so supporting another is a new name in
# $HARNESSES and a new branch in harness_run and nowhere else.
#
# Each adapter answers the same questions: the binary, how a prompt is given
# without a terminal, the flag that picks a model, the flag that grants access to
# the planning checkout, how the session is allowed to act with nobody there to
# approve, and what --no-web turns off. Adapters that have no flag for one of
# them say so in a comment instead of guessing one.

# The harnesses the launcher can drive, in the order "auto" tries them. The
# binary of each is named like the harness. "custom" is not in the list: it is
# chosen on purpose, with DELIVERY_LANE_CMD.
HARNESSES="claude copilot codex opencode pi"

is_harness() {
  case " $HARNESSES custom " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# The prompt that starts a lane. Claude Code, and Copilot CLI inside the
# repository that holds the skills, resolve "/<skill> <args>". Every other case
# is told to read the skill file, which needs no skill discovery from the
# harness: the lane may be in another repository, and not every harness reads
# every skills directory.
#   harness_prompt <harness> <cross-repo: 0|1> <skill file> <arguments>
harness_prompt() {
  case "$1:$2" in
    claude:* | copilot:0) printf '/delivery-implement %s' "$4" ;;
    *) printf 'Read %s and follow it as a skill, with the arguments: %s' "$3" "$4" ;;
  esac
}

# Run one lane's session in the current directory, the lane's worktree, and
# return its exit status.
#   harness_run <harness> <prompt> <model> <add-dir> <plan-dir> <web: 0|1>
# <model> and <add-dir> are empty when there is none to pass. <plan-dir> is the
# checkout holding the planning files, always set.
harness_run() {
  harness="$1" prompt="$2" model="$3" add_dir="$4" plan_dir="$5" web="$6"
  case "$harness" in
    claude)
      # acceptEdits alone denies every shell command in -p mode, and nobody is
      # there to approve one, so the lane could not run a single test. Allowing
      # Bash matches Copilot's --allow-all-tools; the denies still win over it.
      # Web tools are denied outright rather than left unallowed: a developer's
      # own settings may allow them, and --no-web has to hold regardless.
      set -- claude -p "$prompt"
      [ -z "$add_dir" ] || set -- "$@" --add-dir "$add_dir"
      [ -z "$model" ] || set -- "$@" --model "$model"
      set -- "$@" --permission-mode acceptEdits
      if [ "$web" = 1 ]; then
        set -- "$@" --allowedTools Bash WebFetch WebSearch --disallowedTools "Bash(terraform apply:*)" "Bash(terraform destroy:*)"
      else
        set -- "$@" --allowedTools Bash --disallowedTools "Bash(terraform apply:*)" "Bash(terraform destroy:*)" WebFetch WebSearch
      fi
      ;;
    copilot)
      # --allow-all-tools already covers Copilot's web tools; web_search comes
      # from the built-in GitHub MCP server.
      set -- copilot -p "$prompt"
      [ -z "$add_dir" ] || set -- "$@" --add-dir "$add_dir"
      [ -z "$model" ] || set -- "$@" --model "$model"
      set -- "$@" --allow-all-tools --deny-tool 'shell(terraform apply)' --deny-tool 'shell(terraform destroy)'
      [ "$web" = 1 ] || set -- "$@" --excluded-tools web_fetch web_search
      ;;
    codex)
      # exec never asks. The sandbox is what limits it: it writes inside the
      # worktree and, by default, has no network. Web search is a separate
      # opt-in flag Codex does not get here, so --no-web already holds.
      set -- codex exec --sandbox workspace-write
      [ -z "$add_dir" ] || set -- "$@" --add-dir "$add_dir"
      [ -z "$model" ] || set -- "$@" --model "$model"
      set -- "$@" "$prompt"
      ;;
    opencode)
      # --auto approves whatever the config does not deny. The denies travel in
      # the inline config, so they hold whatever the developer's own says.
      # OpenCode has no flag to add a directory; --auto covers reading the
      # planning checkout. The model is "provider/model".
      deny='"bash":{"terraform apply*":"deny","terraform destroy*":"deny"}'
      [ "$web" = 1 ] || deny="$deny,\"webfetch\":\"deny\""
      set -- env "OPENCODE_CONFIG_CONTENT={\"permission\":{$deny}}" opencode run --auto
      [ -z "$model" ] || set -- "$@" --model "$model"
      set -- "$@" "$prompt"
      ;;
    pi)
      # Pi has no permission system, so nothing asks and nothing is denied: run
      # lanes on it in a container or a throwaway machine. Its tools are read,
      # write, edit and bash, so there are no web tools to take away.
      set -- pi -p "$prompt"
      [ -z "$model" ] || set -- "$@" --model "$model"
      ;;
    custom)
      # DELIVERY_LANE_CMD is a shell command line. Its placeholders become
      # references to environment variables, never pasted text, so a prompt
      # holding quotes or $(...) cannot change the command.
      [ -n "${DELIVERY_LANE_CMD:-}" ] || { printf 'ERROR\tDELIVERY_LANE_CMD is not set\n' >&2; return 1; }
      DELIVERY_PROMPT="$prompt" DELIVERY_MODEL="$model" DELIVERY_WORKTREE="$PWD" \
        DELIVERY_PLAN_DIR="$plan_dir" DELIVERY_WEB="$web"
      export DELIVERY_PROMPT DELIVERY_MODEL DELIVERY_WORKTREE DELIVERY_PLAN_DIR DELIVERY_WEB
      # shellcheck disable=SC2016 # the $ is for the command's shell, not this one
      set -- sh -c "$(printf '%s' "$DELIVERY_LANE_CMD" | sed \
        -e 's/{prompt}/"$DELIVERY_PROMPT"/g' \
        -e 's/{model}/"$DELIVERY_MODEL"/g' \
        -e 's/{worktree}/"$DELIVERY_WORKTREE"/g' \
        -e 's/{plan_dir}/"$DELIVERY_PLAN_DIR"/g')"
      ;;
    *)
      printf 'ERROR\tunknown harness: %s\n' "$harness" >&2
      return 1
      ;;
  esac
  "$@"
}
