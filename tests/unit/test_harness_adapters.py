"""Each harness adapter builds exactly the command line its CLI expects.

A stand-in binary per harness records its arguments one per line, so the tests
assert the whole command and not a substring of it. They prove the launcher
passes what the adapter table says; whether a real CLI accepts it is recorded
in docs/harness-validation.md, which is the only place a claim of that kind
belongs.
"""

import json
import subprocess
from pathlib import Path

import pytest

from tests.conftest import SH
from tests.unit.test_launch_lanes_script import (
    CLAIM,
    SKILLS,
    add_task,
    clone_of,
    conf,
    fake_harness,
    git,
    launch_live,
    make_shared_origin,
    wait_for,
    write_tiers,
)

TASK_ARGS = "delivery/tasks/b-001.md --report .lane-report.md"
READ_PROMPT = "Read {skill} and follow it as a skill, with the arguments: " + TASK_ARGS
SLASH_PROMPT = "/delivery-implement " + TASK_ARGS
DENY_TERRAFORM = {"terraform apply*": "deny", "terraform destroy*": "deny"}


def recording_stub(bin_dir: Path, name: str) -> None:
    """Replace a harness stand-in with one that logs each argument on its own line."""
    stub = bin_dir / name
    stub.write_text(
        '#!/bin/sh\nfor arg in "$@"; do printf "ARG %s\\n" "$arg" >> "$FAKE_LOG"; done\n'
        'printf "CONFIG %s\\n" "${OPENCODE_CONFIG_CONTENT:-}" >> "$FAKE_LOG"\n'
        'printf "PWD %s\\n" "$PWD" >> "$FAKE_LOG"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)


def run_lane(
    tmp_path: Path,
    harness: str,
    *extra: str,
    model: str | None = "m-1",
    advisor: str | None = None,
    mapped_for: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Launch one lane on a harness, and return its arguments and what else it logged.

    The build tier maps to ``model`` and ``advisor`` for ``mapped_for``, the lane's
    own harness unless named, or for any harness when it is empty.
    """
    origin_path = make_shared_origin(tmp_path)
    dev = clone_of(tmp_path, origin_path, "devA")
    add_task(dev, "b-001")
    git(dev, "add", "-A")
    git(dev, "commit", "-q", "-m", "add b-001")
    git(dev, "push", "-q", "origin", "HEAD:refs/heads/main")
    log = tmp_path / "agent.log"
    names = ("claude", "copilot", "codex", "opencode", "pi")
    bin_dir = fake_harness(tmp_path, log, names)
    for name in names:
        recording_stub(bin_dir, name)
    env = dict(env or {})
    keys = {"harness": harness if mapped_for is None else mapped_for, "model": model, "advisor": advisor}
    if model is not None or advisor is not None:
        mapping = write_tiers(tmp_path / "t.conf", conf(build={k: v for k, v in keys.items() if v}))
        env["DELIVERY_TIERS"] = str(mapping)
    result = launch_live(
        dev,
        [
            "--claim-script",
            str(CLAIM),
            "--worktree-root",
            str(tmp_path / "lanes"),
            "--harness",
            harness,
            *extra,
            "b-001",
        ],
        bin_dir,
        log,
        isolated=True,
        env_extra=env,
    )
    assert f"LAUNCHED\tb-001\t{harness}" in result.stdout, result.stdout + result.stderr
    wait_for(lambda: any(m in log.read_text(encoding="utf-8") for m in ("PWD ", "VALUE ")))
    lines = log.read_text(encoding="utf-8").splitlines()
    args = [line.removeprefix("ARG ") for line in lines if line.startswith("ARG ")]
    other = {
        line.split(" ", 1)[0]: line.split(" ", 1)[1] if " " in line else ""
        for line in lines
        if not line.startswith("ARG ")
    }
    return args, other


def skill_path() -> str:
    from tests.unit.test_launch_lanes_script import SKILLS  # noqa: PLC0415

    return str(SKILLS / "delivery-orchestrator" / "scripts" / ".." / ".." / "delivery-implement" / "SKILL.md")


class TestCommandLines:
    def test_claude(self, tmp_path: Path) -> None:
        # When a lane launches on claude
        args, _ = run_lane(tmp_path, "claude")

        # Then it gets the slash prompt, the model and its tool rules
        assert args == [
            "-p", SLASH_PROMPT,
            "--model", "m-1",
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Bash", "WebFetch", "WebSearch",
            "--disallowedTools", "Bash(terraform apply:*)", "Bash(terraform destroy:*)",
        ]  # fmt: skip

    def test_copilot(self, tmp_path: Path) -> None:
        # When a lane launches on copilot
        args, _ = run_lane(tmp_path, "copilot")

        # Then it gets the slash prompt, the model and its tool rules
        assert args == [
            "-p", SLASH_PROMPT,
            "--model", "m-1",
            "--allow-all-tools",
            "--deny-tool", "shell(terraform apply)",
            "--deny-tool", "shell(terraform destroy)",
        ]  # fmt: skip

    def test_codex(self, tmp_path: Path) -> None:
        # When a lane launches on codex
        args, _ = run_lane(tmp_path, "codex")

        # Then it runs exec in a workspace sandbox, with a prompt that reads the skill
        assert args[:5] == ["exec", "--sandbox", "workspace-write", "--model", "m-1"]
        assert args[5].startswith("Read ")
        assert args[5].endswith("with the arguments: " + TASK_ARGS)
        assert len(args) == 6  # noqa: PLR2004

    def test_opencode(self, tmp_path: Path) -> None:
        # When a lane launches on opencode
        args, other = run_lane(tmp_path, "opencode")

        # Then its permissions travel in the config, not the arguments
        assert args[:4] == ["run", "--auto", "--model", "m-1"]
        assert args[4].startswith("Read ")
        assert len(args) == 5  # noqa: PLR2004
        assert json.loads(other["CONFIG"]) == {"permission": {"bash": DENY_TERRAFORM}}

    def test_pi(self, tmp_path: Path) -> None:
        # When a lane launches on pi
        args, _ = run_lane(tmp_path, "pi")

        # Then it gets a prompt that reads the skill, then the model
        assert args[0] == "-p"
        assert args[1].startswith("Read ")
        assert args[2:] == ["--model", "m-1"]

    @pytest.mark.parametrize("harness", ["claude", "copilot", "codex", "opencode", "pi"])
    def test_no_model_flag_without_a_mapping(self, tmp_path: Path, harness: str) -> None:
        # When a lane launches with no model mapped
        args, _ = run_lane(tmp_path, harness, model=None)

        # Then no model flag is passed
        assert "--model" not in args

    def test_claude_passes_the_advisor(self, tmp_path: Path) -> None:
        # When a claude lane launches with an advisor mapped
        args, _ = run_lane(tmp_path, "claude", advisor="a-1")

        # Then the advisor follows the model
        assert args[2:6] == ["--model", "m-1", "--advisor", "a-1"]

    @pytest.mark.parametrize("harness", ["copilot", "codex", "opencode", "pi"])
    def test_only_claude_has_an_advisor(self, tmp_path: Path, harness: str) -> None:
        # When another harness launches with an advisor mapped for any harness
        args, _ = run_lane(tmp_path, harness, advisor="a-1", mapped_for="")

        # Then the advisor is dropped
        assert "a-1" not in args

    def test_an_advisor_mapped_for_another_harness_is_not_passed(self, tmp_path: Path) -> None:
        # When a claude lane launches on a tier mapped for copilot
        args, _ = run_lane(tmp_path, "claude", advisor="a-1", mapped_for="copilot")

        # Then neither the model nor the advisor is passed
        assert "--advisor" not in args
        assert "--model" not in args

    def test_the_lane_runs_in_its_worktree(self, tmp_path: Path) -> None:
        # When a lane launches
        _, other = run_lane(tmp_path, "pi")

        # Then the harness runs in the lane's worktree
        assert other["PWD"] == str(tmp_path / "lanes" / "b-001")


class TestWebAccess:
    def test_opencode_denies_web_fetch_when_asked(self, tmp_path: Path) -> None:
        # When an opencode lane launches without web access
        _, other = run_lane(tmp_path, "opencode", "--no-web")

        # Then web fetch is denied in its config
        assert json.loads(other["CONFIG"]) == {"permission": {"bash": DENY_TERRAFORM, "webfetch": "deny"}}

    def test_codex_and_pi_have_no_web_tool_to_take_away(self, tmp_path: Path) -> None:
        # When a codex lane launches with and without web access
        on, _ = run_lane(tmp_path / "on", "codex")
        off, _ = run_lane(tmp_path / "off", "codex", "--no-web")

        # Then the command line is the same
        assert on == off


class TestCustomCommand:
    def test_placeholders_become_the_lanes_values(self, tmp_path: Path) -> None:
        # Given a custom command that logs its placeholders
        template = 'for v in {model} {worktree} {plan_dir}; do printf "VALUE %s\\n" "$v" >> "$FAKE_LOG"; done'

        # When a lane launches on it
        run_lane(tmp_path, "custom", env={"DELIVERY_LANE_CMD": template})

        # Then each placeholder became the lane's value
        wait_for(lambda: (tmp_path / "agent.log").read_text(encoding="utf-8").count("VALUE ") >= 3)  # noqa: PLR2004
        log = (tmp_path / "agent.log").read_text(encoding="utf-8").splitlines()
        values = [line.removeprefix("VALUE ") for line in log if line.startswith("VALUE ")]
        assert values == ["m-1", str(tmp_path / "lanes" / "b-001"), str(tmp_path / "devA")]

    def test_a_hostile_path_is_a_value_and_never_code(self, tmp_path: Path) -> None:
        # Given a worktree root whose name holds a command substitution
        marker = tmp_path / "pwned"
        template = 'printf "VALUE %s\\n" {worktree} >> "$FAKE_LOG"'
        root = tmp_path / f"x $(touch {marker}) y"
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, ("claude",))

        # When a custom lane launches under it
        result = launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(root), "--harness", "custom", "a-001"],
            bin_dir,
            log,
            isolated=True,
            env_extra={"DELIVERY_LANE_CMD": template},
        )

        # Then the path is passed as text and never run
        assert "LAUNCHED\ta-001\tcustom" in result.stdout, result.stdout + result.stderr
        wait_for(lambda: "VALUE" in log.read_text(encoding="utf-8"))
        assert not marker.exists()
        assert str(root / "a-001") in log.read_text(encoding="utf-8")

    def test_it_needs_a_command(self, tmp_path: Path) -> None:
        # Given no DELIVERY_LANE_CMD
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a custom lane is launched
        result = launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "--harness", "custom", "a-001"],
            bin_dir,
            log,
            isolated=True,
        )

        # Then it is skipped, saying what is missing
        assert "SKIP\ta-001\tcustom needs DELIVERY_LANE_CMD to be set" in result.stdout


class TestPrompt:
    """A session is started on a skill by its directory name, so one adapter serves both of a lane's skills."""

    @pytest.mark.parametrize(
        ("harness", "cross", "expected"),
        [
            ("claude", "0", "/delivery-refine t.md --report r.md"),
            ("copilot", "0", "/delivery-refine t.md --report r.md"),
            ("copilot", "1", "Read {skill} and follow it as a skill, with the arguments: t.md --report r.md"),
            ("codex", "0", "Read {skill} and follow it as a skill, with the arguments: t.md --report r.md"),
        ],
    )
    def test_names_the_skill_it_is_given(self, harness: str, cross: str, expected: str) -> None:
        # Given the delivery-refine skill
        skill = str(SKILLS / "delivery-orchestrator" / "scripts" / ".." / ".." / "delivery-refine" / "SKILL.md")
        lib = SKILLS / "delivery-orchestrator" / "scripts" / "harness.sh"

        # When a prompt is built for it
        result = subprocess.run(  # noqa: S603
            [
                SH,
                "-c",
                '. "$1"; harness_prompt "$2" "$3" "$4" "t.md --report r.md"',
                "sh",
                str(lib),
                harness,
                cross,
                skill,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        # Then the prompt names that skill, not delivery-implement
        assert result.stdout == expected.format(skill=skill)
