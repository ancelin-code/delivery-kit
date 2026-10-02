"""Behavioural tests for the lane launcher.

The launcher decides how many agent sessions start and on what, so the tests
exercise its selection logic through ``--dry-run``: nothing is created and no
session is started, but every decision is still made and reported.
"""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.model_labels import ROUTING

SKILLS = Path(__file__).resolve().parents[2] / ".agents" / "skills"
SCRIPT = SKILLS / "fourmee" / "scripts" / "launch-lanes.sh"
CLAIM = SKILLS / "fourmee-status" / "scripts" / "claim.sh"

OK = 0
USAGE_ERROR = 1
NO_LANES = 3

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git are required",
)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603, S607


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "dev@example.com")
    git(repo, "config", "user.name", "devA")
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def add_task(
    repo: Path,
    task_id: str,
    *,
    conflicts_with: str = "",
    model: str = "sonnet",
    effort: str | None = None,
    alone: bool = False,
) -> None:
    tasks = repo / "delivery" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    # effort is optional in the schema, so None writes no line at all: that is
    # the case the medium default has to cover.
    effort_line = "" if effort is None else f"effort: {effort}\n"
    (tasks / f"{task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\ntitle: Do {task_id}\nepic: a\ndepends_on: []\n"
        f"parallel: {str(not alone).lower()}\nconflicts_with: [{conflicts_with}]\nmodel: {model}\n"
        f"{effort_line}"
        "---\n\n## Acceptance criteria\n- observable\n",
        encoding="utf-8",
    )


def launch(
    repo: Path, args: list[str], *, stdin: str | None = None, worktree_root: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "FOURMEE_WORKTREE_ROOT"}
    if worktree_root is not None:
        env["FOURMEE_WORKTREE_ROOT"] = worktree_root
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
        cwd=repo,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def launched_ids(stdout: str) -> list[str]:
    return [line.split("\t")[1] for line in stdout.splitlines() if line.startswith(("WOULD-LAUNCH", "LAUNCHED"))]


class TestLaneSelection:
    def test_launches_the_tasks_it_is_given(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002")
        result = launch(repo, ["--dry-run", "a-001", "a-002"])
        assert result.returncode == OK
        assert launched_ids(result.stdout) == ["a-001", "a-002"]

    def test_respects_the_lane_cap(self, tmp_path: Path) -> None:
        """Readiness is not capacity: more ready tasks than lanes is the normal case."""
        repo = make_repo(tmp_path)
        for n in range(1, 6):
            add_task(repo, f"a-00{n}")
        cap = 2
        result = launch(repo, ["--dry-run", "--max-lanes", str(cap), *[f"a-00{n}" for n in range(1, 6)]])
        assert len(launched_ids(result.stdout)) == cap
        assert f"LANES\t{cap}" in result.stdout

    def test_never_runs_two_conflicting_tasks_together(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002", conflicts_with="a-001")
        result = launch(repo, ["--dry-run", "a-001", "a-002"])
        assert launched_ids(result.stdout) == ["a-001"]
        assert "conflicts with running lane a-001" in result.stdout

    def test_catches_a_conflict_declared_on_only_one_side(self, tmp_path: Path) -> None:
        """A one-sided declaration must still hold when the tasks arrive reversed."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002", conflicts_with="a-001")
        result = launch(repo, ["--dry-run", "a-002", "a-001"])
        assert launched_ids(result.stdout) == ["a-002"]
        assert "conflicts with running lane a-002" in result.stdout

    def test_a_conflicting_task_does_not_consume_a_lane_slot(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002", conflicts_with="a-001")
        add_task(repo, "a-003")
        result = launch(repo, ["--dry-run", "--max-lanes", "2", "a-001", "a-002", "a-003"])
        assert launched_ids(result.stdout) == ["a-001", "a-003"]

    def test_skips_a_task_with_no_file(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "a-999"])
        assert result.returncode == NO_LANES
        assert "no task file" in result.stdout

    def test_dies_when_the_tasks_directory_is_absent(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        assert launch(repo, ["--dry-run", "a-001"]).returncode == USAGE_ERROR

    def test_reads_task_ids_from_stdin(self, tmp_path: Path) -> None:
        """Composes with whatever decided the tasks were ready."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002")
        result = launch(repo, ["--dry-run"], stdin="a-001\na-002\n")
        assert launched_ids(result.stdout) == ["a-001", "a-002"]

    def test_ignores_trailing_columns_on_stdin(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run"], stdin="a-001\tready\t-\tDo a-001\n")
        assert launched_ids(result.stdout) == ["a-001"]


class TestRunsAlone:
    """parallel: false means no other lane of the set runs while this one does."""

    def test_a_task_that_runs_alone_holds_back_the_rest_of_the_batch(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", alone=True)
        add_task(repo, "a-002")
        result = launch(repo, ["--dry-run", "a-001", "a-002"])
        assert launched_ids(result.stdout) == ["a-001"]
        assert "SKIP\ta-002\ta-001 runs alone" in result.stdout

    def test_a_task_that_runs_alone_waits_for_lanes_already_started(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002", alone=True)
        add_task(repo, "a-003")
        result = launch(repo, ["--dry-run", "a-001", "a-002", "a-003"])
        assert launched_ids(result.stdout) == ["a-001", "a-003"]
        assert "runs alone, and this batch already started lanes" in result.stdout

    def test_a_serial_set_launches_one_task(self, tmp_path: Path) -> None:
        """Every task false is what a serial set is; no --max-lanes 1 to remember."""
        repo = make_repo(tmp_path)
        for n in (1, 2, 3):
            add_task(repo, f"a-00{n}", alone=True)
        result = launch(repo, ["--dry-run", "a-001", "a-002", "a-003"])
        assert launched_ids(result.stdout) == ["a-001"]


class TestModelRouting:
    @pytest.mark.parametrize(("label", "expected_harness"), sorted(ROUTING.items()))
    def test_routes_each_label_to_its_harness(self, tmp_path: Path, label: str, expected_harness: str) -> None:
        """The harness column of the conventions table is what is asserted here.

        Routing a label to the wrong side spends the wrong budget, and the two
        do not pool, so the error is not visible until an allowance runs out.
        """
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", model=label)
        result = launch(repo, ["--dry-run", "a-001"])
        assert result.stdout.split("\t")[2] == expected_harness

    def test_an_explicit_harness_overrides_the_label(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", model="sonnet")
        result = launch(repo, ["--dry-run", "--harness", "copilot", "a-001"])
        assert result.stdout.split("\t")[2] == "copilot"

    @pytest.mark.parametrize(
        ("label", "harness", "model"),
        [
            ("opus", "claude", "opus"),
            ("sonnet", "claude", "sonnet"),
            ("haiku", "claude", "haiku"),
            ("opus", "copilot", "claude-opus-5.5"),
            ("sonnet", "copilot", "claude-sonnet-5"),
            ("haiku", "copilot", "claude-haiku-4.5"),
            ("terra", "copilot", "gpt-5.6-terra"),
            ("luna", "copilot", "gpt-6-luna"),
        ],
    )
    def test_passes_each_harness_its_own_model_id(self, tmp_path: Path, label: str, harness: str, model: str) -> None:
        """Copilot rejects a bare label such as "luna" and the lane dies at startup."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", model=label)
        result = launch(repo, ["--dry-run", "--harness", harness, "a-001"])
        assert result.stdout.split("\t")[3] == model

    def test_a_copilot_only_label_cannot_be_forced_onto_claude(self, tmp_path: Path) -> None:
        """Claude Code has no terra; passing the name through would fail inside the lane."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", model="terra")
        result = launch(repo, ["--dry-run", "--harness", "claude", "a-001"])
        assert result.stdout.startswith("SKIP\ta-001\tclaude has no terra model")


class TestLauncherUsage:
    def test_dies_without_task_ids(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        assert launch(repo, ["--dry-run"], stdin="").returncode == USAGE_ERROR

    def test_dies_on_an_unknown_harness(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        assert launch(repo, ["--dry-run", "--harness", "gemini", "a-001"]).returncode == USAGE_ERROR

    def test_dies_on_a_zero_lane_cap(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        assert launch(repo, ["--dry-run", "--max-lanes", "0", "a-001"]).returncode == USAGE_ERROR

    def test_dry_run_creates_no_worktree(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        launch(repo, ["--dry-run", "a-001"])
        assert not (tmp_path / "lanes").exists()
        assert "task/a-001" not in git(repo, "branch", "--list").stdout

    def test_worktrees_default_to_a_directory_named_after_this_repository(self, tmp_path: Path) -> None:
        """Clones side by side must not share ../lanes: task ids repeat across use cases."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "a-001"])
        assert f"\t../lanes/{repo.name}/a-001\t" in result.stdout

    def test_worktree_root_holds_the_task_ids_directly(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "--worktree-root", "/elsewhere/shop", "a-001"])
        assert "\t/elsewhere/shop/a-001\t" in result.stdout

    def test_the_environment_sets_the_worktree_root(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "a-001"], worktree_root="/elsewhere/shop")
        assert "\t/elsewhere/shop/a-001\t" in result.stdout

    def test_the_flag_wins_over_the_environment(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "--worktree-root", "/flag", "a-001"], worktree_root="/env")
        assert "\t/flag/a-001\t" in result.stdout


def make_shared_origin(tmp_path: Path) -> Path:
    """A bare repository with one task, standing in for the shared remote."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)  # noqa: S603, S607
    git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    git(seed, "config", "user.email", "seed@example.com")
    git(seed, "config", "user.name", "Seed")
    add_task(seed, "a-001")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "init")
    git(seed, "push", "-q", str(bare), "HEAD:refs/heads/main")
    return bare


def clone_of(tmp_path: Path, origin_path: Path, name: str) -> Path:
    clone = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(origin_path), str(clone)], check=True)  # noqa: S603, S607
    git(clone, "config", "user.email", f"{name}@example.com")
    git(clone, "config", "user.name", name)
    return clone


def fake_harness(
    tmp_path: Path,
    log: Path,
    names: tuple[str, ...] = ("claude", "copilot"),
    *,
    edits: bool = False,
    fails: bool = False,
) -> Path:
    """A stand-in for claude/copilot that records how it was invoked.

    Only the given names are installed. Defaults to both, or a copilot lane
    falls through to the real CLI on a developer machine and the test
    silently starts a billed session; a single name simulates a machine that
    only has one harness installed. With ``edits`` the session leaves a change
    behind, which the launcher then publishes; with ``fails`` it exits 1, as a
    session does on an expired login or a model the account cannot use.

    A ``gh`` stub is always installed, so a published lane never reaches the
    real forge.
    """
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    edit = 'printf "done\\n" > lane-output.txt\n' if edits else ""
    for name in names:
        stub = bin_dir / name
        stub.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$PWD" >> "$FAKE_LOG"\nprintf "%s\\n" "$*" >> "$FAKE_LOG"\n'
            + edit
            + ("exit 1\n" if fails else ""),
            encoding="utf-8",
        )
        stub.chmod(0o755)
    gh = bin_dir / "gh"
    gh.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "{tmp_path / "gh.log"}"\n'
        '[[ "$1 $2" == "pr view" ]] && exit 1\nprintf "https://example.test/pr/1\\n"\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    log.write_text("", encoding="utf-8")
    return bin_dir


def launch_live(
    repo: Path, args: list[str], bin_dir: Path, log: Path, *, isolated: bool = False
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # A fallback test fakes only one harness name and relies on the other one
    # genuinely being absent. Prepending to the ambient PATH is not enough for
    # that: a real claude or copilot binary installed on this machine would
    # still be found further down it, and the test would start a real,
    # billed session instead of proving the fallback logic. Replacing PATH
    # with just the fake bin dir plus the system dirs the script itself
    # needs (git, awk, bash) closes that gap.
    env["PATH"] = f"{bin_dir}{os.pathsep}/usr/bin:/bin" if isolated else f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["FAKE_LOG"] = str(log)
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class TestLaneStartup:
    """The real path: worktree, claim, and a session actually started."""

    def test_starts_the_agent_inside_the_lane_worktree(self, tmp_path: Path) -> None:
        """A session started in the wrong directory would edit the wrong checkout."""
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        result = launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        assert result.returncode == OK
        recorded = log.read_text(encoding="utf-8")
        assert recorded.strip(), "the harness was never invoked"
        assert str(tmp_path / "lanes" / "a-001") in recorded

    def test_falls_back_to_the_installed_harness_for_a_portable_label(self, tmp_path: Path) -> None:
        """No Anthropic license is required to run this kit.

        opus, sonnet and haiku are Claude models the launcher can also run on
        Copilot CLI. A machine with only a Copilot license has no "claude"
        binary at all, so auto-routing must not skip these lanes.
        """
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        add_task(dev, "b-001", model="opus")
        git(dev, "add", "-A")
        git(dev, "commit", "-q", "-m", "add b-001")
        git(dev, "push", "-q", "origin", "HEAD:refs/heads/main")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, names=("copilot",))

        result = launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "b-001"],
            bin_dir,
            log,
            isolated=True,
        )

        assert result.returncode == OK, result.stderr
        assert result.stdout.strip().startswith("LAUNCHED\tb-001\tcopilot\tclaude-opus-5.5")
        assert log.read_text(encoding="utf-8").strip(), "copilot was never invoked"

    def test_a_copilot_only_label_has_no_fallback(self, tmp_path: Path) -> None:
        """terra has no Claude Code equivalent, so a missing copilot must still skip.

        Falling back to claude for it would silently launch the wrong model.
        """
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        add_task(dev, "b-001", model="terra")
        git(dev, "add", "-A")
        git(dev, "commit", "-q", "-m", "add b-001")
        git(dev, "push", "-q", "origin", "HEAD:refs/heads/main")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, names=("claude",))

        result = launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "b-001"],
            bin_dir,
            log,
            isolated=True,
        )

        assert result.stdout.strip() == "SKIP\tb-001\tcopilot not found on PATH\nLANES\t0"
        assert not log.read_text(encoding="utf-8").strip(), "nothing should have been invoked"

    def test_refuses_to_start_without_a_usable_claim_script(self, tmp_path: Path) -> None:
        """An unclaimed lane is worse than no lane.

        The claim was once optional and skipped in silence, so a launcher run
        without it started every ready task, printed LAUNCHED for each, and left
        five developers free to take the same one.
        """
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        result = launch(repo, ["--claim-script", str(tmp_path / "absent.sh"), "a-001"])

        assert result.returncode == USAGE_ERROR
        assert "claim script not found" in result.stderr
        assert "LAUNCHED" not in result.stdout

    def test_a_broken_claim_script_is_not_reported_as_a_lost_race(self, tmp_path: Path) -> None:
        """Losing a race is routine; a broken claim is a fault that needs fixing.

        Both used to print the same line, so a misconfigured claim script looked
        exactly like somebody else holding every task.
        """
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        broken = tmp_path / "broken-claim.sh"
        broken.write_text("#!/usr/bin/env bash\nexit 9\n", encoding="utf-8")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        result = launch_live(
            dev,
            ["--claim-script", str(broken), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        assert "claim failed (exit 9)" in result.stdout
        assert "already claimed" not in result.stdout
        assert not log.read_text(encoding="utf-8").strip(), "no session may start on a failed claim"

    def test_invokes_the_skill_as_a_slash_command(self, tmp_path: Path) -> None:
        """Prose naming a skill is a suggestion; the slash form is an invocation.

        A harness that reads SKILL.md as an ordinary file instead of registering it
        treats the skill's boundaries as advisory, and the failure is invisible in
        the log. See docs/harness-validation.md, test 4.
        """
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        recorded = log.read_text(encoding="utf-8")
        assert "/fourmee-implement " in recorded
        assert "a-001.md" in recorded, "the task file must reach the skill as its argument"

    def test_passes_the_deny_rules_to_the_session(self, tmp_path: Path) -> None:
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        assert "terraform apply" in log.read_text(encoding="utf-8")

    def test_lets_a_claude_lane_run_shell_commands(self, tmp_path: Path) -> None:
        """acceptEdits alone denies every shell command in -p mode.

        The lane then cannot run a single test, and still exits 0. See
        docs/harness-validation.md, test 6.
        """
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "--harness", "claude", "a-001"],
            bin_dir,
            log,
        )

        recorded = log.read_text(encoding="utf-8")
        assert "--allowedTools Bash" in recorded
        assert "--disallowedTools Bash(terraform apply:*)" in recorded

    @pytest.mark.parametrize(
        ("harness", "web_on", "web_off"),
        [
            ("claude", "--allowedTools Bash WebFetch WebSearch", "WebFetch WebSearch\n"),
            ("copilot", None, "--excluded-tools web_fetch web_search"),
        ],
    )
    def test_web_access_is_on_unless_turned_off(
        self, tmp_path: Path, harness: str, web_on: str | None, web_off: str
    ) -> None:
        """Web access is the default and a prompt-injection path, so it has an off switch.

        --no-web has to hold on both harnesses: on Claude Code by an explicit
        deny, since a developer's own settings may allow the tools; on Copilot
        by removing both web tools, one of which comes from its GitHub MCP server.
        """
        for web in ("on", "off"):
            root = tmp_path / web
            origin_path = make_shared_origin(root)
            dev = clone_of(root, origin_path, "devA")
            log = root / "agent.log"
            bin_dir = fake_harness(root, log)
            flags = ["--no-web"] if web == "off" else []

            launch_live(
                dev,
                [
                    "--claim-script",
                    str(CLAIM),
                    "--worktree-root",
                    str(root / "lanes"),
                    "--harness",
                    harness,
                    *flags,
                    "a-001",
                ],
                bin_dir,
                log,
            )

            recorded = log.read_text(encoding="utf-8")
            if web == "on":
                assert web_on is None or web_on in recorded
                assert "--excluded-tools" not in recorded
            else:
                assert web_off in recorded
                assert "--allowedTools Bash WebFetch" not in recorded

    def test_asks_the_lane_for_a_report(self, tmp_path: Path) -> None:
        """The report becomes the pull request body, so the lane has to write it."""
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        assert "a-001.md --report .lane-report.md" in log.read_text(encoding="utf-8")

    def test_a_clean_session_ends_in_a_draft_pull_request(self, tmp_path: Path) -> None:
        """The session leaves its change uncommitted; the launcher publishes it."""
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, edits=True)

        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        gh_log = tmp_path / "gh.log"
        deadline = time.monotonic() + 20
        while "pr create" not in (gh_log.read_text(encoding="utf-8") if gh_log.exists() else ""):
            assert time.monotonic() < deadline, "the lane was never published"
            time.sleep(0.2)
        assert "--draft" in gh_log.read_text(encoding="utf-8")
        files = git(origin_path, "ls-tree", "-r", "--name-only", "task/a-001").stdout.split()
        assert "lane-output.txt" in files

    def test_a_session_that_fails_at_startup_gives_its_task_back(self, tmp_path: Path) -> None:
        """Otherwise the task stays held by a lane that never ran."""
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, fails=True)
        logs = tmp_path / "lanelogs"

        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "--log-dir", str(logs), "a-001"],
            bin_dir,
            log,
        )

        lane_log = logs / "a-001.log"
        deadline = time.monotonic() + 20
        while "RELEASED" not in (lane_log.read_text(encoding="utf-8") if lane_log.exists() else ""):
            assert time.monotonic() < deadline, "the claim was never released"
            time.sleep(0.2)
        refs = git(origin_path, "for-each-ref", "--format=%(refname)", "refs/heads/task/").stdout
        assert "refs/heads/task/a-001" not in refs
        assert not (tmp_path / "lanes" / "a-001").exists()
        assert not (tmp_path / "gh.log").exists(), "a failed session must not be published"

    def test_a_task_that_runs_alone_waits_for_another_developers_lane(self, tmp_path: Path) -> None:
        """The batch is not the whole picture: in-flight work lives on the remote."""
        origin_path = make_shared_origin(tmp_path)
        seed = clone_of(tmp_path, origin_path, "seed2")
        add_task(seed, "a-002", alone=True)
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "add a-002")
        git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")
        holder = clone_of(tmp_path, origin_path, "devA")
        latecomer = clone_of(tmp_path, origin_path, "devB")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        launch_live(
            holder, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lA"), "a-001"], bin_dir, log
        )
        result = launch_live(
            latecomer, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lB"), "a-002"], bin_dir, log
        )

        assert "SKIP\ta-002\truns alone, and tasks are in flight: a-001" in result.stdout
        assert not (tmp_path / "lB" / "a-002").exists()

    def test_nothing_starts_while_a_task_that_runs_alone_is_in_flight(self, tmp_path: Path) -> None:
        origin_path = make_shared_origin(tmp_path)
        seed = clone_of(tmp_path, origin_path, "seed2")
        add_task(seed, "a-002", alone=True)
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "add a-002")
        git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")
        holder = clone_of(tmp_path, origin_path, "devA")
        latecomer = clone_of(tmp_path, origin_path, "devB")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        launch_live(
            holder, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lA"), "a-002"], bin_dir, log
        )
        result = launch_live(
            latecomer, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lB"), "a-001"], bin_dir, log
        )

        assert "SKIP\ta-001\ta-002 runs alone and is in flight" in result.stdout

    def test_a_lane_starts_from_the_remote_not_a_stale_checkout(self, tmp_path: Path) -> None:
        """A dependency merged on the forge must be in the next lane's base.

        Nothing updates the launching checkout when a pull request merges, so a
        lane branched from its HEAD lacked the code it depended on, and its pull
        request conflicted. Found by running the follow loop on a real task set.
        """
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        merger = clone_of(tmp_path, origin_path, "merger")
        (merger / "dependency.py").write_text("DONE = True\n", encoding="utf-8")
        git(merger, "add", "dependency.py")
        git(merger, "commit", "-q", "-m", "feat: the dependency merges")
        git(merger, "push", "-q", "origin", "HEAD:refs/heads/main")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        result = launch_live(
            dev, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"], bin_dir, log
        )

        assert result.returncode == OK, result.stdout + result.stderr
        assert (tmp_path / "lanes" / "a-001" / "dependency.py").exists()

    def test_a_repository_without_origin_head_still_launches(self, tmp_path: Path) -> None:
        """A repository created locally and pushed has no origin/HEAD; a clone does."""
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        git(dev, "remote", "set-head", "origin", "--delete")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        result = launch_live(
            dev, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"], bin_dir, log
        )

        assert result.returncode == OK, result.stdout + result.stderr
        assert (tmp_path / "lanes" / "a-001").is_dir()

    def test_pins_reasoning_effort_on_both_harnesses(self, tmp_path: Path) -> None:
        """Effort is a cost axis the model label does not cover.

        Unset, each harness applies its own default, so the cost of a lane stops
        following from its task file. The flag is spelled differently per harness,
        which is exactly the kind of difference that rots silently.
        """
        for harness, flag in (("claude", "--effort"), ("copilot", "--reasoning-effort")):
            origin_path = make_shared_origin(tmp_path / harness)
            dev = clone_of(tmp_path / harness, origin_path, "devA")
            log = tmp_path / harness / "agent.log"
            bin_dir = fake_harness(tmp_path / harness, log)

            launch_live(
                dev,
                [
                    "--claim-script",
                    str(CLAIM),
                    "--worktree-root",
                    str(tmp_path / harness / "lanes"),
                    "--harness",
                    harness,
                    "a-001",
                ],
                bin_dir,
                log,
            )

            recorded = log.read_text(encoding="utf-8")
            assert f"{flag} medium" in recorded, f"{harness} lane ran at the harness default effort"

    def test_effort_is_overridable_per_batch(self, tmp_path: Path) -> None:
        """Medium is the default, not the only value.

        A batch rerun after a round of medium-effort lanes stalled is the case
        this exists for, and editing the script to get it would apply to every
        future run on that machine.
        """
        for harness, flag in (("claude", "--effort"), ("copilot", "--reasoning-effort")):
            origin_path = make_shared_origin(tmp_path / harness)
            dev = clone_of(tmp_path / harness, origin_path, "devA")
            log = tmp_path / harness / "agent.log"
            bin_dir = fake_harness(tmp_path / harness, log)

            launch_live(
                dev,
                [
                    "--claim-script",
                    str(CLAIM),
                    "--worktree-root",
                    str(tmp_path / harness / "lanes"),
                    "--harness",
                    harness,
                    "--effort",
                    "high",
                    "a-001",
                ],
                bin_dir,
                log,
            )

            recorded = log.read_text(encoding="utf-8")
            assert f"{flag} high" in recorded, f"{harness} lane ignored --effort"
            assert f"{flag} medium" not in recorded

    @pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh", "max"])
    def test_accepts_every_portable_effort_level(self, tmp_path: Path, level: str) -> None:
        """Both CLIs accept these five; Copilot also takes none and minimal.

        Accepting only the intersection keeps a batch launchable on either side.
        """
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "--effort", level, "a-001"])
        assert result.returncode == 0, result.stderr
        assert result.stdout.split("\t")[4] == level

    @pytest.mark.parametrize("level", ["low", "high", "xhigh", "max"])
    def test_a_task_sets_its_own_effort(self, tmp_path: Path, level: str) -> None:
        """The tier is the class of judgement; the effort is how much of it.

        They are independent: a design-bearing task can want opus at high while
        a planning task wants opus at medium.
        """
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", effort=level)
        result = launch(repo, ["--dry-run", "a-001"])
        assert result.stdout.split("\t")[4] == level

    def test_a_task_without_an_effort_runs_at_medium(self, tmp_path: Path) -> None:
        """effort is optional, so most task files will not carry one."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "a-001"])
        assert result.stdout.split("\t")[4] == "medium"

    def test_the_batch_flag_overrides_every_task(self, tmp_path: Path) -> None:
        """Mirrors --harness overriding the harness the model label implies.

        Holding a launch down when a budget is nearly spent has to beat what the
        task files ask for, or the override is not one.
        """
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", effort="max")
        add_task(repo, "a-002")
        result = launch(repo, ["--dry-run", "--effort", "low", "a-001", "a-002"])
        efforts = [row.split("\t")[4] for row in result.stdout.strip().splitlines() if row.startswith("WOULD-LAUNCH")]
        assert efforts == ["low", "low"], result.stdout

    def test_skips_a_task_whose_effort_no_harness_accepts(self, tmp_path: Path) -> None:
        """Only an unvalidated task set reaches here.

        Passing the value through would fail inside the harness, after the claim
        and the worktree already exist, which is a lost task rather than a
        skipped one.
        """
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", effort="minimal")
        result = launch(repo, ["--dry-run", "a-001"])
        assert result.stdout.startswith("SKIP\ta-001\tunknown effort")

    def test_rejects_an_effort_level_one_harness_would_refuse(self, tmp_path: Path) -> None:
        """minimal is valid for Copilot and not for Claude Code."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "--effort", "minimal", "a-001"])
        assert result.returncode == USAGE_ERROR
        assert "--effort must be" in result.stderr

    def test_writes_a_session_log_for_the_lane(self, tmp_path: Path) -> None:
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)
        logs = tmp_path / "lanelogs"

        launch_live(
            dev,
            [
                "--claim-script",
                str(CLAIM),
                "--worktree-root",
                str(tmp_path / "lanes"),
                "--log-dir",
                str(logs),
                "a-001",
            ],
            bin_dir,
            log,
        )

        assert (logs / "a-001.log").exists()

    def test_claims_the_task_on_the_remote(self, tmp_path: Path) -> None:
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        refs = git(origin_path, "for-each-ref", "--format=%(refname)", "refs/heads/task/").stdout
        assert "refs/heads/task/a-001" in refs

    def test_a_lost_claim_leaves_no_worktree_or_branch_behind(self, tmp_path: Path) -> None:
        """Losing a claim is routine. It must not litter the loser's checkout."""
        origin_path = make_shared_origin(tmp_path)
        holder = clone_of(tmp_path, origin_path, "devA")
        latecomer = clone_of(tmp_path, origin_path, "devB")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        launch_live(
            holder,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanesA"), "a-001"],
            bin_dir,
            log,
        )
        result = launch_live(
            latecomer,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanesB"), "a-001"],
            bin_dir,
            log,
        )

        assert result.returncode == NO_LANES
        assert "already claimed" in result.stdout
        assert not (tmp_path / "lanesB" / "a-001").exists()
        assert "task/a-001" not in git(latecomer, "branch", "--list").stdout
