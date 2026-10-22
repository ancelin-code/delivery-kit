"""Behavioural tests for the lane launcher.

The launcher decides how many agent sessions start and on what, so the tests
exercise its selection logic through ``--dry-run``: nothing is created and no
session is started, but every decision is still made and reported.
"""

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.conftest import SH
from tests.unit.tiers import TIERS

SKILLS = Path(__file__).resolve().parents[2] / ".agents" / "skills"
SCRIPT = SKILLS / "delivery-orchestrator" / "scripts" / "launch-lanes.sh"
CLAIM = SKILLS / "delivery-status" / "scripts" / "claim.sh"

OK = 0
USAGE_ERROR = 1
NO_LANES = 3

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git is required",
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
    tier: str | None = "build",
    alone: bool = False,
) -> None:
    tasks = repo / "delivery" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / f"{task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\ntitle: Do {task_id}\nepic: a\ndepends_on: []\n"
        f"parallel: {str(not alone).lower()}\nconflicts_with: [{conflicts_with}]\n"
        f"{'' if tier is None else f'tier: {tier}\n'}"
        "---\n\n## Acceptance criteria\n- observable\n",
        encoding="utf-8",
    )


def clean_env(repo: Path) -> dict[str, str]:
    """The ambient environment without the developer's own Delivery Kit settings.

    A real ~/.config/delivery-kit/tiers.conf or DELIVERY_HARNESS on the machine
    running the suite would otherwise change what the launcher decides.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("DELIVERY_")}
    env["XDG_CONFIG_HOME"] = str(repo.parent / "no-user-config")
    return env


def conf(**tiers: dict[str, str]) -> str:
    """A tiers.conf in git-config form: one section per tier, then its keys."""
    return "".join(
        f"[{tier}]\n" + "".join(f"\t{key} = {value}\n" for key, value in keys.items()) for tier, keys in tiers.items()
    )


def write_tiers(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def launch(
    repo: Path,
    args: list[str],
    *,
    stdin: str | None = None,
    worktree_root: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = clean_env(repo)
    if worktree_root is not None:
        env["DELIVERY_WORKTREE_ROOT"] = worktree_root
    env.update(env_extra or {})
    return subprocess.run(  # noqa: S603
        [SH, str(SCRIPT), *args],
        cwd=repo,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def wait_for(condition: Callable[[], object], seconds: float = 10.0) -> None:
    """Poll until a lane's background session has done what the test looks for."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.1)
    message = "timed out waiting for the lane's session"
    raise AssertionError(message)


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


def fields(stdout: str) -> list[str]:
    """The tab-separated fields of the first launch line."""
    return stdout.splitlines()[0].split("\t")


ALL_HARNESSES = "claude copilot codex opencode pi"
HARNESS, MODEL = 2, 3


class TestTiers:
    """A tier is a hint. Which harness and model it means is the developer's mapping."""

    @pytest.mark.parametrize("tier", TIERS)
    def test_every_documented_tier_is_launchable(self, tmp_path: Path, tier: str) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier=tier)
        result = launch(repo, ["--dry-run", "a-001"])
        assert result.returncode == OK, result.stderr
        assert result.stdout.startswith("WOULD-LAUNCH\ta-001")

    def test_an_unmapped_tier_leaves_harness_and_model_to_the_harness(self, tmp_path: Path) -> None:
        """No mapping, no model flag: the harness applies its own default."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")
        result = launch(repo, ["--dry-run", "a-001"])
        assert fields(result.stdout)[HARNESS] == "auto"
        assert fields(result.stdout)[MODEL] == "default"

    def test_a_task_with_no_tier_is_a_build_task(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier=None)
        mapping = write_tiers(tmp_path / "tiers.conf", conf(build={"model": "sonnet"}))
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(mapping)})
        assert fields(result.stdout)[MODEL] == "sonnet"

    def test_an_unknown_tier_in_a_task_file_is_skipped_and_names_the_real_ones(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="gpt4")
        result = launch(repo, ["--dry-run", "a-001"])
        assert result.stdout.startswith("SKIP\ta-001\tunknown tier in task file: gpt4 (expected plan, build, or chore)")

    def test_a_mapping_picks_the_harness_and_the_model(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")
        add_task(repo, "a-002", tier="chore")
        mapping = write_tiers(
            tmp_path / "tiers.conf",
            conf(plan={"harness": "claude", "model": "opus"}, chore={"harness": "copilot", "model": "gpt-6-luna"}),
        )
        result = launch(repo, ["--dry-run", "a-001", "a-002"], env_extra={"DELIVERY_TIERS": str(mapping)})
        rows = [line.split("\t") for line in result.stdout.splitlines() if line.startswith("WOULD")]
        assert [r[HARNESS : MODEL + 1] for r in rows] == [["claude", "opus"], ["copilot", "gpt-6-luna"]]

    def test_harness_and_model_are_each_optional(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="build")
        add_task(repo, "a-002", tier="chore")
        mapping = write_tiers(tmp_path / "tiers.conf", conf(build={"model": "sonnet"}, chore={"harness": "claude"}))
        result = launch(repo, ["--dry-run", "a-001", "a-002"], env_extra={"DELIVERY_TIERS": str(mapping)})
        rows = [line.split("\t") for line in result.stdout.splitlines() if line.startswith("WOULD")]
        assert [r[HARNESS : MODEL + 1] for r in rows] == [["auto", "sonnet"], ["claude", "default"]]

    def test_a_mapping_applies_only_to_the_harness_it_names(self, tmp_path: Path) -> None:
        """A model id means nothing to another harness: passing it through ends the session at startup."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="chore")
        mapping = write_tiers(tmp_path / "tiers.conf", conf(chore={"harness": "copilot", "model": "gpt-6-luna"}))
        result = launch(repo, ["--dry-run", "--harness", "claude", "a-001"], env_extra={"DELIVERY_TIERS": str(mapping)})
        assert fields(result.stdout)[HARNESS : MODEL + 1] == ["claude", "default"]

    def test_the_flag_wins_over_the_mapping_and_the_environment(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")
        mapping = write_tiers(tmp_path / "tiers.conf", conf(plan={"harness": "claude", "model": "opus"}))
        env = {"DELIVERY_TIERS": str(mapping), "DELIVERY_HARNESS": "claude"}
        result = launch(repo, ["--dry-run", "--harness", "copilot", "a-001"], env_extra=env)
        assert fields(result.stdout)[HARNESS] == "copilot"

    def test_the_mapping_wins_over_the_environment(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")
        mapping = write_tiers(tmp_path / "tiers.conf", conf(plan={"harness": "copilot"}))
        env = {"DELIVERY_TIERS": str(mapping), "DELIVERY_HARNESS": "claude"}
        result = launch(repo, ["--dry-run", "a-001"], env_extra=env)
        assert fields(result.stdout)[HARNESS] == "copilot"

    def test_the_environment_picks_the_harness_when_nothing_else_does(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_HARNESS": "copilot"})
        assert fields(result.stdout)[HARNESS] == "copilot"

    def test_auto_is_accepted_as_a_choice(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        assert launch(repo, ["--dry-run", "--harness", "auto", "a-001"]).returncode == OK
        assert launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_HARNESS": "auto"}).returncode == OK

    def test_the_developers_file_is_read_from_the_xdg_config_directory(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        mapping = conf(build={"harness": "claude", "model": "sonnet"})
        write_tiers(tmp_path / "xdg" / "delivery-kit" / "tiers.conf", mapping)
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})
        assert fields(result.stdout)[HARNESS : MODEL + 1] == ["claude", "sonnet"]

    def test_the_project_file_is_the_default_and_the_developer_wins_per_tier(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")
        add_task(repo, "a-002", tier="build")
        write_tiers(
            repo / "delivery" / "tiers.conf",
            conf(plan={"model": "opus"}, build={"model": "sonnet"}),
        )
        mine = write_tiers(tmp_path / "mine.conf", conf(build={"model": "haiku"}))
        result = launch(repo, ["--dry-run", "a-001", "a-002"], env_extra={"DELIVERY_TIERS": str(mine)})
        rows = [line.split("\t") for line in result.stdout.splitlines() if line.startswith("WOULD")]
        assert [r[MODEL] for r in rows] == ["opus", "haiku"]

    def test_the_first_file_to_name_a_tier_decides_all_of_it(self, tmp_path: Path) -> None:
        """A developer's model must not be paired with a harness the project chose."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="build")
        write_tiers(repo / "delivery" / "tiers.conf", conf(build={"harness": "copilot", "model": "team-model"}))
        mine = write_tiers(tmp_path / "mine.conf", conf(build={"model": "my-model"}))
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(mine)})
        assert fields(result.stdout)[HARNESS : MODEL + 1] == ["auto", "my-model"]

    def test_comments_and_blank_lines_are_ignored(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        text = "# my models\n\n[build]\n; the cheap one\n\tmodel = sonnet  # my pick\n"
        mapping = write_tiers(tmp_path / "t.conf", text)
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(mapping)})
        assert fields(result.stdout)[MODEL] == "sonnet"

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("[buidl]\nmodel = x\n", "t.conf: unknown tier 'buidl' (expected plan, build, or chore)"),
            ("[build]\nmodle = x\n", "t.conf: unknown key 'build.modle' (expected harness, model, or advisor)"),
            (
                "[build]\nharness = gemini\n",
                f"t.conf: unknown harness 'gemini' (expected one of: {ALL_HARNESSES} custom)",
            ),
            ("[build]\nmodel = a\nmodel = b\n", "t.conf: build.model is set twice"),
            ("[build]\nmodel\n", "t.conf: 'build.model' has no value"),
            ('[build "x"]\nmodel = a\n', "t.conf: unexpected key 'build.x.model'"),
            ("[build\nmodel = x\n", "bad config line 1 in file"),
        ],
    )
    def test_a_malformed_mapping_stops_the_launch_and_says_where(self, tmp_path: Path, text: str, message: str) -> None:
        """A typo in a mapping must not quietly fall back to the harness default."""
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        mapping = write_tiers(tmp_path / "t.conf", text)
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(mapping)})
        assert result.returncode == USAGE_ERROR
        assert message in result.stderr

    def test_a_named_mapping_file_that_does_not_exist_is_an_error(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(tmp_path / "nope.conf")})
        assert result.returncode == USAGE_ERROR
        assert "DELIVERY_TIERS names a missing file" in result.stderr

    def test_an_unknown_harness_in_the_environment_is_an_error(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_HARNESS": "gemini"})
        assert result.returncode == USAGE_ERROR
        assert "DELIVERY_HARNESS must be" in result.stderr


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
        """Clones side by side must not share ../lanes: task ids repeat across projects."""
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
            '#!/bin/sh\nprintf "%s\\n" "$PWD" >> "$FAKE_LOG"\nprintf "%s\\n" "$*" >> "$FAKE_LOG"\n'
            + edit
            + ("exit 1\n" if fails else ""),
            encoding="utf-8",
        )
        stub.chmod(0o755)
    gh = bin_dir / "gh"
    gh.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{tmp_path / "gh.log"}"\n'
        '[ "$1 $2" = "pr view" ] && exit 1\nprintf "https://example.test/pr/1\\n"\n',
        encoding="utf-8",
    )
    gh.chmod(0o755)
    log.write_text("", encoding="utf-8")
    return bin_dir


def launch_live(
    repo: Path,
    args: list[str],
    bin_dir: Path,
    log: Path,
    *,
    isolated: bool = False,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = clean_env(repo)
    env.update(env_extra or {})
    # A selection test fakes only one harness name and relies on the other one
    # genuinely being absent. Prepending to the ambient PATH is not enough for
    # that: a real claude or copilot binary installed on this machine would
    # still be found further down it, and the test would start a real,
    # billed session instead of proving the fallback logic. Replacing PATH
    # with just the fake bin dir plus the system dirs the script itself
    # needs (git, awk, sh) closes that gap.
    if isolated:
        env["PATH"] = f"{bin_dir}{os.pathsep}/usr/bin:/bin"
    else:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["FAKE_LOG"] = str(log)
    return subprocess.run(  # noqa: S603
        [SH, str(SCRIPT), *args],
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

    @staticmethod
    def one_task_remote(tmp_path: Path, tier: str = "build") -> Path:
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        add_task(dev, "b-001", tier=tier)
        git(dev, "add", "-A")
        git(dev, "commit", "-q", "-m", "add b-001")
        git(dev, "push", "-q", "origin", "HEAD:refs/heads/main")
        return dev

    @staticmethod
    def go(dev: Path, tmp_path: Path, bin_dir: Path, log: Path, *extra: str, env: dict[str, str] | None = None):
        return launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), *extra, "b-001"],
            bin_dir,
            log,
            isolated=True,
            env_extra=env,
        )

    def test_auto_uses_the_first_harness_that_is_installed(self, tmp_path: Path) -> None:
        """No license for one vendor is required: a machine with only Copilot launches on Copilot."""
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, names=("copilot",))

        result = self.go(dev, tmp_path, bin_dir, log)

        assert result.returncode == OK, result.stderr
        assert result.stdout.strip().startswith("LAUNCHED\tb-001\tcopilot\tdefault")
        assert log.read_text(encoding="utf-8").strip(), "copilot was never invoked"

    def test_auto_prefers_claude_when_both_are_installed(self, tmp_path: Path) -> None:
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        result = self.go(dev, tmp_path, bin_dir, log)

        assert result.stdout.strip().startswith("LAUNCHED\tb-001\tclaude\tdefault")

    def test_no_installed_harness_skips_the_lane(self, tmp_path: Path) -> None:
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, names=())

        result = self.go(dev, tmp_path, bin_dir, log)

        assert result.stdout.strip() == f"SKIP\tb-001\tno supported harness on PATH ({ALL_HARNESSES})\nLANES\t0"

    def test_a_harness_somebody_chose_is_never_swapped_for_another(self, tmp_path: Path) -> None:
        """A lane on a harness nobody asked for would spend an allowance nobody meant to spend."""
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, names=("claude",))
        mapping = write_tiers(tmp_path / "t.conf", conf(build={"harness": "copilot"}))

        result = self.go(dev, tmp_path, bin_dir, log, env={"DELIVERY_TIERS": str(mapping)})

        assert result.stdout.strip() == "SKIP\tb-001\tcopilot not found on PATH\nLANES\t0"
        assert not log.read_text(encoding="utf-8").strip(), "nothing should have been invoked"

    def test_an_unmapped_tier_passes_no_model_flag(self, tmp_path: Path) -> None:
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        self.go(dev, tmp_path, bin_dir, log)

        wait_for(lambda: log.read_text(encoding="utf-8").strip())
        assert "--model" not in log.read_text(encoding="utf-8")

    @pytest.mark.parametrize("harness", ["claude", "copilot"])
    def test_a_mapped_model_reaches_the_harness_it_is_for(self, tmp_path: Path, harness: str) -> None:
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)
        mapping = write_tiers(tmp_path / "t.conf", conf(build={"harness": harness, "model": "some-model"}))

        result = self.go(dev, tmp_path, bin_dir, log, env={"DELIVERY_TIERS": str(mapping)})

        assert f"LAUNCHED\tb-001\t{harness}\tsome-model" in result.stdout
        wait_for(lambda: log.read_text(encoding="utf-8").strip())
        assert "--model some-model" in log.read_text(encoding="utf-8")

    def test_a_model_mapped_for_another_harness_is_not_passed_on(self, tmp_path: Path) -> None:
        dev = self.one_task_remote(tmp_path, tier="chore")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)
        mapping = write_tiers(tmp_path / "t.conf", conf(chore={"harness": "copilot", "model": "gpt-6-luna"}))

        result = self.go(dev, tmp_path, bin_dir, log, "--harness", "claude", env={"DELIVERY_TIERS": str(mapping)})

        assert "LAUNCHED\tb-001\tclaude\tdefault" in result.stdout
        wait_for(lambda: log.read_text(encoding="utf-8").strip())
        assert "gpt-6-luna" not in log.read_text(encoding="utf-8")

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
        broken.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
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
        assert "/delivery-implement " in recorded
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


def test_refuses_to_launch_without_delivery_implement_beside_it(tmp_path: Path) -> None:
    """A lane is told to follow delivery-implement; without it the session would run with no skill."""
    skills = tmp_path / "skills"
    shutil.copytree(SKILLS, skills)
    shutil.rmtree(skills / "delivery-implement")
    result = subprocess.run(  # noqa: S603
        [SH, str(skills / "delivery-orchestrator" / "scripts" / "launch-lanes.sh"), "--dry-run", "a-001"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "delivery-implement is not installed beside delivery-orchestrator" in result.stderr
