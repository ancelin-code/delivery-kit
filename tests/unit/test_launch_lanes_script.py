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
        # Given two tasks
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002")

        # When both are planned
        result = launch(repo, ["--dry-run", "a-001", "a-002"])

        # Then both would launch
        assert result.returncode == OK
        assert launched_ids(result.stdout) == ["a-001", "a-002"]

    def test_respects_the_lane_cap(self, tmp_path: Path) -> None:
        """Readiness is not capacity: more ready tasks than lanes is the normal case."""
        # Given five tasks and a cap of two
        repo = make_repo(tmp_path)
        for n in range(1, 6):
            add_task(repo, f"a-00{n}")
        cap = 2

        # When they are planned
        result = launch(repo, ["--dry-run", "--max-lanes", str(cap), *[f"a-00{n}" for n in range(1, 6)]])

        # Then two would launch
        assert len(launched_ids(result.stdout)) == cap
        assert f"LANES\t{cap}" in result.stdout

    def test_never_runs_two_conflicting_tasks_together(self, tmp_path: Path) -> None:
        # Given a-002 conflicting with a-001
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002", conflicts_with="a-001")

        # When both are planned
        result = launch(repo, ["--dry-run", "a-001", "a-002"])

        # Then only a-001 would launch
        assert launched_ids(result.stdout) == ["a-001"]
        assert "conflicts with running lane a-001" in result.stdout

    def test_catches_a_conflict_declared_on_only_one_side(self, tmp_path: Path) -> None:
        """A one-sided declaration must still hold when the tasks arrive reversed."""
        # Given a conflict declared only on a-002
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002", conflicts_with="a-001")

        # When they are planned in reverse order
        result = launch(repo, ["--dry-run", "a-002", "a-001"])

        # Then only a-002 would launch
        assert launched_ids(result.stdout) == ["a-002"]
        assert "conflicts with running lane a-002" in result.stdout

    def test_a_conflicting_task_does_not_consume_a_lane_slot(self, tmp_path: Path) -> None:
        # Given a-002 conflicting with a-001, and a cap of two
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002", conflicts_with="a-001")
        add_task(repo, "a-003")

        # When three tasks are planned
        result = launch(repo, ["--dry-run", "--max-lanes", "2", "a-001", "a-002", "a-003"])

        # Then the skipped one leaves its slot to a-003
        assert launched_ids(result.stdout) == ["a-001", "a-003"]

    def test_skips_a_task_with_no_file(self, tmp_path: Path) -> None:
        # Given no file for a-999
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When a-999 is planned
        result = launch(repo, ["--dry-run", "a-999"])

        # Then it is skipped and nothing launches
        assert result.returncode == NO_LANES
        assert "no task file" in result.stdout

    def test_dies_when_the_tasks_directory_is_absent(self, tmp_path: Path) -> None:
        # Given a repository with no tasks directory
        repo = make_repo(tmp_path)

        # When a task is planned
        result = launch(repo, ["--dry-run", "a-001"])

        # Then it is a usage error
        assert result.returncode == USAGE_ERROR

    def test_reads_task_ids_from_stdin(self, tmp_path: Path) -> None:
        """Composes with whatever decided the tasks were ready."""
        # Given two tasks
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002")

        # When their ids come on stdin
        result = launch(repo, ["--dry-run"], stdin="a-001\na-002\n")

        # Then both would launch
        assert launched_ids(result.stdout) == ["a-001", "a-002"]

    def test_ignores_trailing_columns_on_stdin(self, tmp_path: Path) -> None:
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When its status.sh row comes on stdin
        result = launch(repo, ["--dry-run"], stdin="a-001\tready\t-\tDo a-001\n")

        # Then only the id is used
        assert launched_ids(result.stdout) == ["a-001"]


class TestRunsAlone:
    """parallel: false means no other lane of the set runs while this one does."""

    def test_a_task_that_runs_alone_holds_back_the_rest_of_the_batch(self, tmp_path: Path) -> None:
        # Given a-001 runs alone
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", alone=True)
        add_task(repo, "a-002")

        # When it is planned with a-002
        result = launch(repo, ["--dry-run", "a-001", "a-002"])

        # Then a-002 waits
        assert launched_ids(result.stdout) == ["a-001"]
        assert "SKIP\ta-002\ta-001 runs alone" in result.stdout

    def test_a_task_that_runs_alone_waits_for_lanes_already_started(self, tmp_path: Path) -> None:
        # Given a-002 runs alone, between two shared tasks
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        add_task(repo, "a-002", alone=True)
        add_task(repo, "a-003")

        # When the three are planned
        result = launch(repo, ["--dry-run", "a-001", "a-002", "a-003"])

        # Then a-002 waits for the lanes started before it
        assert launched_ids(result.stdout) == ["a-001", "a-003"]
        assert "runs alone, and this batch already started lanes" in result.stdout

    def test_a_serial_set_launches_one_task(self, tmp_path: Path) -> None:
        """Every task false is what a serial set is; no --max-lanes 1 to remember."""
        # Given three tasks that each run alone
        repo = make_repo(tmp_path)
        for n in (1, 2, 3):
            add_task(repo, f"a-00{n}", alone=True)

        # When they are planned
        result = launch(repo, ["--dry-run", "a-001", "a-002", "a-003"])

        # Then only the first would launch
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
        # Given a task on a documented tier
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier=tier)

        # When it is planned
        result = launch(repo, ["--dry-run", "a-001"])

        # Then it would launch
        assert result.returncode == OK, result.stderr
        assert result.stdout.startswith("WOULD-LAUNCH\ta-001")

    def test_an_unmapped_tier_leaves_harness_and_model_to_the_harness(self, tmp_path: Path) -> None:
        """No mapping, no model flag: the harness applies its own default."""
        # Given a plan task and no mapping
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")

        # When it is planned
        result = launch(repo, ["--dry-run", "a-001"])

        # Then harness and model are left to defaults
        assert fields(result.stdout)[HARNESS] == "auto"
        assert fields(result.stdout)[MODEL] == "default"

    def test_a_task_with_no_tier_is_a_build_task(self, tmp_path: Path) -> None:
        # Given a task with no tier, and a build mapping
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier=None)
        mapping = write_tiers(tmp_path / "tiers.conf", conf(build={"model": "sonnet"}))

        # When it is planned
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(mapping)})

        # Then it gets the build model
        assert fields(result.stdout)[MODEL] == "sonnet"

    def test_an_unknown_tier_in_a_task_file_is_skipped_and_names_the_real_ones(self, tmp_path: Path) -> None:
        # Given a task on an unknown tier
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="gpt4")

        # When it is planned
        result = launch(repo, ["--dry-run", "a-001"])

        # Then it is skipped, naming the real tiers
        assert result.stdout.startswith("SKIP\ta-001\tunknown tier in task file: gpt4 (expected plan, build, or chore)")

    def test_a_mapping_picks_the_harness_and_the_model(self, tmp_path: Path) -> None:
        # Given plan and chore tiers mapped to different harnesses
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")
        add_task(repo, "a-002", tier="chore")
        mapping = write_tiers(
            tmp_path / "tiers.conf",
            conf(plan={"harness": "claude", "model": "opus"}, chore={"harness": "copilot", "model": "gpt-6-luna"}),
        )

        # When a task of each is planned
        result = launch(repo, ["--dry-run", "a-001", "a-002"], env_extra={"DELIVERY_TIERS": str(mapping)})
        rows = [line.split("\t") for line in result.stdout.splitlines() if line.startswith("WOULD")]

        # Then each gets its tier's harness and model
        assert [r[HARNESS : MODEL + 1] for r in rows] == [["claude", "opus"], ["copilot", "gpt-6-luna"]]

    def test_harness_and_model_are_each_optional(self, tmp_path: Path) -> None:
        # Given build mapping only a model, chore only a harness
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="build")
        add_task(repo, "a-002", tier="chore")
        mapping = write_tiers(tmp_path / "tiers.conf", conf(build={"model": "sonnet"}, chore={"harness": "claude"}))

        # When a task of each is planned
        result = launch(repo, ["--dry-run", "a-001", "a-002"], env_extra={"DELIVERY_TIERS": str(mapping)})
        rows = [line.split("\t") for line in result.stdout.splitlines() if line.startswith("WOULD")]

        # Then the missing half is left to defaults
        assert [r[HARNESS : MODEL + 1] for r in rows] == [["auto", "sonnet"], ["claude", "default"]]

    def test_a_mapping_applies_only_to_the_harness_it_names(self, tmp_path: Path) -> None:
        """A model id means nothing to another harness: passing it through ends the session at startup."""
        # Given chore mapped to a copilot model
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="chore")
        mapping = write_tiers(tmp_path / "tiers.conf", conf(chore={"harness": "copilot", "model": "gpt-6-luna"}))

        # When a chore task is planned on claude
        result = launch(repo, ["--dry-run", "--harness", "claude", "a-001"], env_extra={"DELIVERY_TIERS": str(mapping)})

        # Then the copilot model is not used
        assert fields(result.stdout)[HARNESS : MODEL + 1] == ["claude", "default"]

    def test_the_flag_wins_over_the_mapping_and_the_environment(self, tmp_path: Path) -> None:
        # Given a mapping and the environment both naming claude
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")
        mapping = write_tiers(tmp_path / "tiers.conf", conf(plan={"harness": "claude", "model": "opus"}))
        env = {"DELIVERY_TIERS": str(mapping), "DELIVERY_HARNESS": "claude"}

        # When --harness copilot is given
        result = launch(repo, ["--dry-run", "--harness", "copilot", "a-001"], env_extra=env)

        # Then copilot is used
        assert fields(result.stdout)[HARNESS] == "copilot"

    def test_the_mapping_wins_over_the_environment(self, tmp_path: Path) -> None:
        # Given a mapping naming copilot and the environment claude
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")
        mapping = write_tiers(tmp_path / "tiers.conf", conf(plan={"harness": "copilot"}))
        env = {"DELIVERY_TIERS": str(mapping), "DELIVERY_HARNESS": "claude"}

        # When a task is planned
        result = launch(repo, ["--dry-run", "a-001"], env_extra=env)

        # Then copilot is used
        assert fields(result.stdout)[HARNESS] == "copilot"

    def test_the_environment_picks_the_harness_when_nothing_else_does(self, tmp_path: Path) -> None:
        # Given no mapping and DELIVERY_HARNESS set
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When a task is planned
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_HARNESS": "copilot"})

        # Then the environment's harness is used
        assert fields(result.stdout)[HARNESS] == "copilot"

    def test_auto_is_accepted_as_a_choice(self, tmp_path: Path) -> None:
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When auto is passed as the flag
        result = launch(repo, ["--dry-run", "--harness", "auto", "a-001"])

        # Then it is accepted
        assert result.returncode == OK

        # When auto is set in the environment
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_HARNESS": "auto"})

        # Then it is accepted
        assert result.returncode == OK

    def test_the_developers_file_is_read_from_the_xdg_config_directory(self, tmp_path: Path) -> None:
        # Given a mapping in the XDG config directory
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        mapping = conf(build={"harness": "claude", "model": "sonnet"})
        write_tiers(tmp_path / "xdg" / "delivery-kit" / "tiers.conf", mapping)

        # When a task is planned
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"XDG_CONFIG_HOME": str(tmp_path / "xdg")})

        # Then that mapping is used
        assert fields(result.stdout)[HARNESS : MODEL + 1] == ["claude", "sonnet"]

    def test_the_project_file_is_the_default_and_the_developer_wins_per_tier(self, tmp_path: Path) -> None:
        # Given a project mapping for plan and build, and a developer's for build
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="plan")
        add_task(repo, "a-002", tier="build")
        write_tiers(
            repo / "delivery" / "tiers.conf",
            conf(plan={"model": "opus"}, build={"model": "sonnet"}),
        )
        mine = write_tiers(tmp_path / "mine.conf", conf(build={"model": "haiku"}))

        # When a task of each is planned
        result = launch(repo, ["--dry-run", "a-001", "a-002"], env_extra={"DELIVERY_TIERS": str(mine)})
        rows = [line.split("\t") for line in result.stdout.splitlines() if line.startswith("WOULD")]

        # Then plan follows the project and build the developer
        assert [r[MODEL] for r in rows] == ["opus", "haiku"]

    def test_the_first_file_to_name_a_tier_decides_all_of_it(self, tmp_path: Path) -> None:
        """A developer's model must not be paired with a harness the project chose."""
        # Given the project maps build to a harness and model, the developer only a model
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="build")
        write_tiers(repo / "delivery" / "tiers.conf", conf(build={"harness": "copilot", "model": "team-model"}))
        mine = write_tiers(tmp_path / "mine.conf", conf(build={"model": "my-model"}))

        # When a build task is planned
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(mine)})

        # Then the developer's tier is taken whole, without the project's harness
        assert fields(result.stdout)[HARNESS : MODEL + 1] == ["auto", "my-model"]

    def test_comments_and_blank_lines_are_ignored(self, tmp_path: Path) -> None:
        # Given a mapping with comments, blank lines and indentation
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        text = "# my models\n\n[build]\n; the cheap one\n\tmodel = sonnet  # my pick\n"
        mapping = write_tiers(tmp_path / "t.conf", text)

        # When a task is planned
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(mapping)})

        # Then the model is read
        assert fields(result.stdout)[MODEL] == "sonnet"

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("[buidl]\nmodel = x\n", "t.conf: unknown tier 'buidl' (expected plan, build, or chore)"),
            (
                "[build]\nmodle = x\n",
                "t.conf: unknown key 'build.modle' (expected harness, model, advisor, or reviewer)",
            ),
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
        # Given a malformed mapping
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")
        mapping = write_tiers(tmp_path / "t.conf", text)

        # When a task is planned
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(mapping)})

        # Then the launch stops, naming the file and the problem
        assert result.returncode == USAGE_ERROR
        assert message in result.stderr

    def test_a_named_mapping_file_that_does_not_exist_is_an_error(self, tmp_path: Path) -> None:
        # Given DELIVERY_TIERS naming a missing file
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When a task is planned
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_TIERS": str(tmp_path / "nope.conf")})

        # Then it is a usage error
        assert result.returncode == USAGE_ERROR
        assert "DELIVERY_TIERS names a missing file" in result.stderr

    def test_an_unknown_harness_in_the_environment_is_an_error(self, tmp_path: Path) -> None:
        # Given an unknown DELIVERY_HARNESS
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When a task is planned
        result = launch(repo, ["--dry-run", "a-001"], env_extra={"DELIVERY_HARNESS": "gemini"})

        # Then it is a usage error
        assert result.returncode == USAGE_ERROR
        assert "DELIVERY_HARNESS must be" in result.stderr


class TestLauncherUsage:
    def test_dies_without_task_ids(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)

        # When nothing is given to plan
        result = launch(repo, ["--dry-run"], stdin="")

        # Then it is a usage error
        assert result.returncode == USAGE_ERROR

    def test_dies_on_an_unknown_harness(self, tmp_path: Path) -> None:
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When an unknown harness is asked for
        result = launch(repo, ["--dry-run", "--harness", "gemini", "a-001"])

        # Then it is a usage error
        assert result.returncode == USAGE_ERROR

    def test_dies_on_a_zero_lane_cap(self, tmp_path: Path) -> None:
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When the cap is zero
        result = launch(repo, ["--dry-run", "--max-lanes", "0", "a-001"])

        # Then it is a usage error
        assert result.returncode == USAGE_ERROR

    def test_dry_run_creates_no_worktree(self, tmp_path: Path) -> None:
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When a dry run plans it
        launch(repo, ["--dry-run", "a-001"])

        # Then no worktree or branch exists
        assert not (tmp_path / "lanes").exists()
        assert "task/a-001" not in git(repo, "branch", "--list").stdout

    def test_worktrees_default_to_a_directory_named_after_this_repository(self, tmp_path: Path) -> None:
        """Clones side by side must not share ../lanes: task ids repeat across projects."""
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When it is planned
        result = launch(repo, ["--dry-run", "a-001"])

        # Then its worktree sits under a directory named after the repository
        assert f"\t../lanes/{repo.name}/a-001\t" in result.stdout

    def test_worktree_root_holds_the_task_ids_directly(self, tmp_path: Path) -> None:
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When a worktree root is given
        result = launch(repo, ["--dry-run", "--worktree-root", "/elsewhere/shop", "a-001"])

        # Then the worktree sits directly under it
        assert "\t/elsewhere/shop/a-001\t" in result.stdout

    def test_the_environment_sets_the_worktree_root(self, tmp_path: Path) -> None:
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When the environment sets the worktree root
        result = launch(repo, ["--dry-run", "a-001"], worktree_root="/elsewhere/shop")

        # Then the worktree sits directly under it
        assert "\t/elsewhere/shop/a-001\t" in result.stdout

    def test_the_flag_wins_over_the_environment(self, tmp_path: Path) -> None:
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When both the flag and the environment set a root
        result = launch(repo, ["--dry-run", "--worktree-root", "/flag", "a-001"], worktree_root="/env")

        # Then the flag's root is used
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
    fails_on: str | None = None,
) -> Path:
    """A stand-in for claude/copilot that records how it was invoked.

    Only the given names are installed. Defaults to both, or a copilot lane
    falls through to the real CLI on a developer machine and the test
    silently starts a billed session; a single name simulates a machine that
    only has one harness installed. With ``edits`` the session leaves a change
    behind, which the launcher then publishes; with ``fails`` it exits 1, as a
    session does on an expired login or a model the account cannot use, and with
    ``fails_on`` it exits 1 only when its arguments contain that text.

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
            + ("exit 1\n" if fails else "")
            + (f'case "$*" in *{fails_on}*) exit 1 ;; esac\n' if fails_on else ""),
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
        # Given a clone of the shared remote
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        result = launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        # Then the harness ran in the lane's worktree
        assert result.returncode == OK
        recorded = log.read_text(encoding="utf-8")
        assert recorded.strip(), "the harness was never invoked"
        assert str(tmp_path / "lanes" / "a-001") in recorded

    def test_the_lane_branch_pushes_to_itself(self, tmp_path: Path) -> None:
        """A lane started from the default branch must not track it, or a plain push goes astray."""
        # Given a clone of the shared remote
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"

        # When a lane is launched
        result = launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            fake_harness(tmp_path, log),
            log,
        )

        # Then its branch's upstream is its own remote branch
        assert result.returncode == OK
        upstream = git(tmp_path / "lanes" / "a-001", "rev-parse", "--abbrev-ref", "task/a-001@{upstream}")
        assert upstream.stdout.strip() == "origin/task/a-001"

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
        # Given a machine with only copilot
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, names=("copilot",))

        # When a lane is launched
        result = self.go(dev, tmp_path, bin_dir, log)

        # Then it runs on copilot
        assert result.returncode == OK, result.stderr
        assert result.stdout.strip().startswith("LAUNCHED\tb-001\tcopilot\tdefault")
        assert log.read_text(encoding="utf-8").strip(), "copilot was never invoked"

    def test_auto_prefers_claude_when_both_are_installed(self, tmp_path: Path) -> None:
        # Given a machine with claude and copilot
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        result = self.go(dev, tmp_path, bin_dir, log)

        # Then it runs on claude
        assert result.stdout.strip().startswith("LAUNCHED\tb-001\tclaude\tdefault")

    def test_no_installed_harness_skips_the_lane(self, tmp_path: Path) -> None:
        # Given a machine with no harness
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, names=())

        # When a lane is launched
        result = self.go(dev, tmp_path, bin_dir, log)

        # Then it is skipped, listing what was looked for
        assert result.stdout.strip() == f"SKIP\tb-001\tno supported harness on PATH ({ALL_HARNESSES})\nLANES\t0"

    def test_a_harness_somebody_chose_is_never_swapped_for_another(self, tmp_path: Path) -> None:
        """A lane on a harness nobody asked for would spend an allowance nobody meant to spend."""
        # Given a mapping choosing copilot on a machine with only claude
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, names=("claude",))
        mapping = write_tiers(tmp_path / "t.conf", conf(build={"harness": "copilot"}))

        # When a lane is launched
        result = self.go(dev, tmp_path, bin_dir, log, env={"DELIVERY_TIERS": str(mapping)})

        # Then it is skipped and nothing runs
        assert result.stdout.strip() == "SKIP\tb-001\tcopilot not found on PATH\nLANES\t0"
        assert not log.read_text(encoding="utf-8").strip(), "nothing should have been invoked"

    def test_an_unmapped_tier_passes_no_model_flag(self, tmp_path: Path) -> None:
        # Given no mapping
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        self.go(dev, tmp_path, bin_dir, log)

        # Then no model flag reaches the harness
        wait_for(lambda: log.read_text(encoding="utf-8").strip())
        assert "--model" not in log.read_text(encoding="utf-8")

    @pytest.mark.parametrize("harness", ["claude", "copilot"])
    def test_a_mapped_model_reaches_the_harness_it_is_for(self, tmp_path: Path, harness: str) -> None:
        # Given build mapped to a harness and model
        dev = self.one_task_remote(tmp_path)
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)
        mapping = write_tiers(tmp_path / "t.conf", conf(build={"harness": harness, "model": "some-model"}))

        # When a lane is launched
        result = self.go(dev, tmp_path, bin_dir, log, env={"DELIVERY_TIERS": str(mapping)})

        # Then that harness gets that model
        assert f"LAUNCHED\tb-001\t{harness}\tsome-model" in result.stdout
        wait_for(lambda: log.read_text(encoding="utf-8").strip())
        assert "--model some-model" in log.read_text(encoding="utf-8")

    def test_a_model_mapped_for_another_harness_is_not_passed_on(self, tmp_path: Path) -> None:
        # Given chore mapped to a copilot model
        dev = self.one_task_remote(tmp_path, tier="chore")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)
        mapping = write_tiers(tmp_path / "t.conf", conf(chore={"harness": "copilot", "model": "gpt-6-luna"}))

        # When a chore lane is launched on claude
        result = self.go(dev, tmp_path, bin_dir, log, "--harness", "claude", env={"DELIVERY_TIERS": str(mapping)})

        # Then the copilot model never reaches claude
        assert "LAUNCHED\tb-001\tclaude\tdefault" in result.stdout
        wait_for(lambda: log.read_text(encoding="utf-8").strip())
        assert "gpt-6-luna" not in log.read_text(encoding="utf-8")

    def test_refuses_to_start_without_a_usable_claim_script(self, tmp_path: Path) -> None:
        """An unclaimed lane is worse than no lane.

        The claim was once optional and skipped in silence, so a launcher run
        without it started every ready task, printed LAUNCHED for each, and left
        five developers free to take the same one.
        """
        # Given a claim script that does not exist
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When a lane is launched
        result = launch(repo, ["--claim-script", str(tmp_path / "absent.sh"), "a-001"])

        # Then it is a usage error and nothing launches
        assert result.returncode == USAGE_ERROR
        assert "claim script not found" in result.stderr
        assert "LAUNCHED" not in result.stdout

    def test_a_broken_claim_script_is_not_reported_as_a_lost_race(self, tmp_path: Path) -> None:
        """Losing a race is routine; a broken claim is a fault that needs fixing.

        Both used to print the same line, so a misconfigured claim script looked
        exactly like somebody else holding every task.
        """
        # Given a claim script that exits 9
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        broken = tmp_path / "broken-claim.sh"
        broken.write_text("#!/bin/sh\nexit 9\n", encoding="utf-8")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        result = launch_live(
            dev,
            ["--claim-script", str(broken), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        # Then the failure is reported as such, and no session starts
        assert "claim failed (exit 9)" in result.stdout
        assert "already claimed" not in result.stdout
        assert not log.read_text(encoding="utf-8").strip(), "no session may start on a failed claim"

    def test_invokes_the_skill_as_a_slash_command(self, tmp_path: Path) -> None:
        """Prose naming a skill is a suggestion; the slash form is an invocation.

        A harness that reads SKILL.md as an ordinary file instead of registering it
        treats the skill's boundaries as advisory, and the failure is invisible in
        the log. See docs/harness-validation.md, test 4.
        """
        # Given a clone of the shared remote
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        # Then the skill is invoked by slash command with the task file
        recorded = log.read_text(encoding="utf-8")
        assert "/delivery-implement " in recorded
        assert "a-001.md" in recorded, "the task file must reach the skill as its argument"

    def test_passes_the_deny_rules_to_the_session(self, tmp_path: Path) -> None:
        # Given a clone of the shared remote
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        # Then the session gets the deny rules
        assert "terraform apply" in log.read_text(encoding="utf-8")

    def test_lets_a_claude_lane_run_shell_commands(self, tmp_path: Path) -> None:
        """acceptEdits alone denies every shell command in -p mode.

        The lane then cannot run a single test, and still exits 0. See
        docs/harness-validation.md, test 6.
        """
        # Given a clone of the shared remote
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a claude lane is launched
        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "--harness", "claude", "a-001"],
            bin_dir,
            log,
        )

        # Then it may run shell commands, minus the denied ones
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
            # Given a fresh clone for each setting, with --no-web for off
            root = tmp_path / web
            origin_path = make_shared_origin(root)
            dev = clone_of(root, origin_path, "devA")
            log = root / "agent.log"
            bin_dir = fake_harness(root, log)
            flags = ["--no-web"] if web == "off" else []

            # When a lane is launched
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

            # Then the web tools follow the setting
            recorded = log.read_text(encoding="utf-8")
            if web == "on":
                assert web_on is None or web_on in recorded
                assert "--excluded-tools" not in recorded
            else:
                assert web_off in recorded
                assert "--allowedTools Bash WebFetch" not in recorded

    def test_asks_the_lane_for_a_report(self, tmp_path: Path) -> None:
        """The report becomes the pull request body, so the lane has to write it."""
        # Given a clone of the shared remote
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        # Then the session is asked for the report
        assert "a-001.md --report .lane-report.md" in log.read_text(encoding="utf-8")

    def test_a_clean_session_ends_in_a_draft_pull_request(self, tmp_path: Path) -> None:
        """The session leaves its change uncommitted; the launcher publishes it."""
        # Given a session that leaves a change
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, edits=True)

        # When a lane is launched
        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        # Then the change is pushed and a draft pull request opens
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
        # Given a session that exits 1
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log, fails=True)
        logs = tmp_path / "lanelogs"

        # When a lane is launched
        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "--log-dir", str(logs), "a-001"],
            bin_dir,
            log,
        )

        # Then the claim, worktree and pull request are all gone
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
        # Given devA holding a-001, and a-002 that runs alone
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

        # When devB launches a-002
        result = launch_live(
            latecomer, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lB"), "a-002"], bin_dir, log
        )

        # Then it waits for devA's lane
        assert "SKIP\ta-002\truns alone, and tasks are in flight: a-001" in result.stdout
        assert not (tmp_path / "lB" / "a-002").exists()

    def test_nothing_starts_while_a_task_that_runs_alone_is_in_flight(self, tmp_path: Path) -> None:
        # Given devA holding a-002, which runs alone
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

        # When devB launches a-001
        result = launch_live(
            latecomer, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lB"), "a-001"], bin_dir, log
        )

        # Then it waits
        assert "SKIP\ta-001\ta-002 runs alone and is in flight" in result.stdout

    def test_a_lane_starts_from_the_remote_not_a_stale_checkout(self, tmp_path: Path) -> None:
        """A dependency merged on the forge must be in the next lane's base.

        Nothing updates the launching checkout when a pull request merges, so a
        lane branched from its HEAD lacked the code it depended on, and its pull
        request conflicted. Found by running the follow loop on a real task set.
        """
        # Given a dependency merged on the remote since the clone
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        merger = clone_of(tmp_path, origin_path, "merger")
        (merger / "dependency.py").write_text("DONE = True\n", encoding="utf-8")
        git(merger, "add", "dependency.py")
        git(merger, "commit", "-q", "-m", "feat: the dependency merges")
        git(merger, "push", "-q", "origin", "HEAD:refs/heads/main")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        result = launch_live(
            dev, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"], bin_dir, log
        )

        # Then its worktree has the dependency
        assert result.returncode == OK, result.stdout + result.stderr
        assert (tmp_path / "lanes" / "a-001" / "dependency.py").exists()

    def test_a_repository_without_origin_head_still_launches(self, tmp_path: Path) -> None:
        """A repository created locally and pushed has no origin/HEAD; a clone does."""
        # Given a clone without origin/HEAD
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        git(dev, "remote", "set-head", "origin", "--delete")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        result = launch_live(
            dev, ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"], bin_dir, log
        )

        # Then its worktree exists
        assert result.returncode == OK, result.stdout + result.stderr
        assert (tmp_path / "lanes" / "a-001").is_dir()

    def test_writes_a_session_log_for_the_lane(self, tmp_path: Path) -> None:
        # Given a clone of the shared remote
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)
        logs = tmp_path / "lanelogs"

        # When a lane is launched with a log directory
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

        # Then the lane's log is there
        assert (logs / "a-001.log").exists()

    def test_claims_the_task_on_the_remote(self, tmp_path: Path) -> None:
        # Given a clone of the shared remote
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        bin_dir = fake_harness(tmp_path, log)

        # When a lane is launched
        launch_live(
            dev,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"), "a-001"],
            bin_dir,
            log,
        )

        # Then the claim branch is on the remote
        refs = git(origin_path, "for-each-ref", "--format=%(refname)", "refs/heads/task/").stdout
        assert "refs/heads/task/a-001" in refs

    def test_a_lost_claim_leaves_no_worktree_or_branch_behind(self, tmp_path: Path) -> None:
        """Losing a claim is routine. It must not litter the loser's checkout."""
        # Given devA holding a-001
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

        # When devB launches it too
        result = launch_live(
            latecomer,
            ["--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanesB"), "a-001"],
            bin_dir,
            log,
        )

        # Then devB is left with no worktree or branch
        assert result.returncode == NO_LANES
        assert "already claimed" in result.stdout
        assert not (tmp_path / "lanesB" / "a-001").exists()
        assert "task/a-001" not in git(latecomer, "branch", "--list").stdout


def test_refuses_to_launch_without_delivery_implement_beside_it(tmp_path: Path) -> None:
    """A lane is told to follow delivery-implement; without it the session would run with no skill."""
    # Given an install without delivery-implement
    skills = tmp_path / "skills"
    shutil.copytree(SKILLS, skills)
    shutil.rmtree(skills / "delivery-implement")

    # When the launcher runs from it
    result = subprocess.run(  # noqa: S603
        [SH, str(skills / "delivery-orchestrator" / "scripts" / "launch-lanes.sh"), "--dry-run", "a-001"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then it refuses, naming the missing skill
    assert result.returncode == 1
    assert "delivery-implement is not installed beside delivery-orchestrator" in result.stderr


REFINE_HARNESS, REFINE_MODEL = 4, 5


class TestRefineSelection:
    """The refinement session reviews on a stronger model than the one that wrote the change."""

    def rows(self, repo: Path, tmp_path: Path, mapping: str, *args: str) -> list[list[str]]:
        tiers = write_tiers(tmp_path / "tiers.conf", mapping)
        result = launch(repo, ["--dry-run", *args], env_extra={"DELIVERY_TIERS": str(tiers)})
        assert result.returncode == OK, result.stderr
        return [line.split("\t") for line in result.stdout.splitlines() if line.startswith("WOULD-LAUNCH")]

    def test_each_tier_is_reviewed_one_tier_up(self, tmp_path: Path) -> None:
        # Given a task on each tier, each tier mapped to a model
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="chore")
        add_task(repo, "a-002", tier="build")
        add_task(repo, "a-003", tier="plan")
        mapping = conf(
            chore={"harness": "claude", "model": "haiku"},
            build={"harness": "claude", "model": "sonnet"},
            plan={"harness": "claude", "model": "opus"},
        )

        # When they are planned
        rows = self.rows(repo, tmp_path, mapping, "a-001", "a-002", "a-003")

        # Then each is reviewed on the tier above's model, plan on its own
        assert [r[MODEL : REFINE_MODEL + 1] for r in rows] == [
            ["haiku", "claude", "sonnet"],
            ["sonnet", "claude", "opus"],
            ["opus", "claude", "opus"],
        ]

    def test_the_tier_above_may_review_on_another_harness(self, tmp_path: Path) -> None:
        # Given build on copilot and plan on claude
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="build")
        mapping = conf(build={"harness": "copilot", "model": "gpt-6"}, plan={"harness": "claude", "model": "opus"})

        # When a build task is planned
        row = self.rows(repo, tmp_path, mapping, "a-001")[0]

        # Then it is reviewed on claude
        assert row[HARNESS : REFINE_MODEL + 1] == ["copilot", "gpt-6", "claude", "opus"]

    def test_a_tier_s_own_reviewer_wins_on_its_harness(self, tmp_path: Path) -> None:
        # Given build with its own reviewer
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="build")
        mapping = conf(
            build={"harness": "copilot", "model": "gpt-6", "reviewer": "gpt-6-pro"},
            plan={"harness": "claude", "model": "opus"},
        )

        # When a build task is planned
        row = self.rows(repo, tmp_path, mapping, "a-001")[0]

        # Then the reviewer is used on build's harness
        assert row[REFINE_HARNESS : REFINE_MODEL + 1] == ["copilot", "gpt-6-pro"]

    def test_unmapped_tiers_review_on_the_harness_default(self, tmp_path: Path) -> None:
        # Given no mapping
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="build")

        # When a task is planned
        result = launch(repo, ["--dry-run", "a-001"])

        # Then the review uses the defaults
        assert fields(result.stdout)[REFINE_HARNESS : REFINE_MODEL + 1] == ["auto", "default"]

    def test_the_harness_flag_holds_for_the_review_too(self, tmp_path: Path) -> None:
        # Given plan mapped to claude
        repo = make_repo(tmp_path)
        add_task(repo, "a-001", tier="build")
        mapping = conf(plan={"harness": "claude", "model": "opus"})

        # When a build task is planned with --harness copilot
        row = self.rows(repo, tmp_path, mapping, "--harness", "copilot", "a-001")[0]

        # Then the review stays on copilot
        assert row[REFINE_HARNESS : REFINE_MODEL + 1] == ["copilot", "default"]

    def test_no_refine_turns_it_off(self, tmp_path: Path) -> None:
        # Given one task
        repo = make_repo(tmp_path)
        add_task(repo, "a-001")

        # When it is planned with --no-refine
        result = launch(repo, ["--dry-run", "--no-refine", "a-001"])

        # Then no review is planned
        assert fields(result.stdout)[REFINE_HARNESS : REFINE_MODEL + 1] == ["-", "-"]


class TestRefineSession:
    """A lane is two sessions: delivery-implement, then delivery-refine on its change."""

    def run(
        self,
        tmp_path: Path,
        *extra: str,
        mapping: str | None = None,
        forced: str | None = "claude",
        **harness: object,
    ) -> tuple[Path, Path]:
        """Run one lane; ``forced`` is the --harness value, and None leaves the choice to the tiers alone."""
        origin_path = make_shared_origin(tmp_path)
        dev = clone_of(tmp_path, origin_path, "devA")
        log = tmp_path / "agent.log"
        logs = tmp_path / "lanelogs"
        env = {}
        if mapping is not None:
            env["DELIVERY_TIERS"] = str(write_tiers(tmp_path / "tiers.conf", mapping))
        launch_live(
            dev,
            [
                "--claim-script", str(CLAIM), "--worktree-root", str(tmp_path / "lanes"),
                "--log-dir", str(logs), *(["--harness", forced] if forced else []), *extra, "a-001",
            ],
            fake_harness(tmp_path, log, **harness),
            log,
            isolated=forced is None,
            env_extra=env,
        )  # fmt: skip
        lane_log = logs / "a-001.log"
        wait_for(lambda: lane_log.exists() and any(
            word in lane_log.read_text(encoding="utf-8") for word in ("PUBLISHED", "NOTHING", "RELEASED", "ERROR")
        ))  # fmt: skip
        return log, lane_log

    @staticmethod
    def prompts(log: Path) -> list[str]:
        return [line for line in log.read_text(encoding="utf-8").splitlines() if line.startswith("-p /delivery")]

    def test_the_change_is_refined_on_the_tier_above_before_it_is_published(self, tmp_path: Path) -> None:
        # Given build on sonnet and plan on opus, and a session that leaves a change
        mapping = conf(build={"harness": "claude", "model": "sonnet"}, plan={"harness": "claude", "model": "opus"})

        # When a lane runs
        log, lane_log = self.run(tmp_path, mapping=mapping, edits=True)

        # Then implement runs on sonnet, refine on opus, then the lane publishes
        prompts = self.prompts(log)
        assert [p.split()[1] for p in prompts] == ["/delivery-implement", "/delivery-refine"]
        assert prompts[0].startswith("-p /delivery-implement delivery/tasks/a-001.md --report .lane-report.md")
        assert "--model sonnet" in prompts[0]
        assert prompts[1].startswith("-p /delivery-refine delivery/tasks/a-001.md --report .lane-report.md")
        assert "--model opus" in prompts[1]
        assert "REFINE\tclaude\topus" in lane_log.read_text(encoding="utf-8")
        assert "PUBLISHED" in lane_log.read_text(encoding="utf-8")

    def test_an_advisor_without_a_model_stays_an_advisor(self, tmp_path: Path) -> None:
        # Given a tier above with an advisor but no model
        mapping = conf(build={"harness": "claude", "model": "sonnet"}, plan={"harness": "claude", "advisor": "opus"})

        # When a lane runs
        log, _ = self.run(tmp_path, mapping=mapping, edits=True)

        # Then the review gets the advisor and no model
        refine = self.prompts(log)[1]
        assert "--advisor opus" in refine
        assert "--model" not in refine

    @pytest.mark.parametrize("above", ["copilot", "custom"])
    def test_the_lane_harness_reviews_when_the_tier_above_cannot_run(self, tmp_path: Path, above: str) -> None:
        """copilot is not installed, and custom has no DELIVERY_LANE_CMD."""
        # Given a tier above on a harness that cannot run here
        mapping = conf(build={"harness": "claude", "model": "sonnet"}, plan={"harness": above, "model": "opus"})

        # When a lane runs
        log, lane_log = self.run(tmp_path, mapping=mapping, forced=None, names=("claude",), edits=True)

        # Then the lane's own harness reviews, on its default model
        assert [p.split()[1] for p in self.prompts(log)] == ["/delivery-implement", "/delivery-refine"]
        assert "REFINE\tclaude\tdefault" in lane_log.read_text(encoding="utf-8")

    def test_nothing_to_refine_when_the_implementation_left_no_change(self, tmp_path: Path) -> None:
        # When a lane runs and leaves no change
        log, lane_log = self.run(tmp_path)

        # Then no refinement runs
        assert [p.split()[1] for p in self.prompts(log)] == ["/delivery-implement"]
        assert "REFINE" not in lane_log.read_text(encoding="utf-8")

    def test_no_refine_publishes_the_implementation_as_it_is(self, tmp_path: Path) -> None:
        # When a lane runs with --no-refine
        log, lane_log = self.run(tmp_path, "--no-refine", edits=True)

        # Then only implement runs, and the lane publishes
        assert [p.split()[1] for p in self.prompts(log)] == ["/delivery-implement"]
        assert "PUBLISHED" in lane_log.read_text(encoding="utf-8")

    def test_a_failed_refinement_still_publishes_and_says_so(self, tmp_path: Path) -> None:
        """The implementation was validated; losing it to a failed review would waste it."""
        # When a lane runs and its refinement fails
        _, lane_log = self.run(tmp_path, edits=True, fails_on="delivery-refine")

        # Then the lane publishes, and the log and report say it failed
        text = lane_log.read_text(encoding="utf-8")
        assert "REFINE-FAILED\t1" in text
        assert "PUBLISHED" in text
        report = (tmp_path / "lanes" / "a-001" / ".lane-report.md").read_text(encoding="utf-8")
        assert "## Refinement" in report
        assert "failed (exit 1)" in report


def test_refuses_to_launch_without_delivery_refine_beside_it(tmp_path: Path) -> None:
    # Given an install without delivery-refine
    skills = tmp_path / "skills"
    shutil.copytree(SKILLS, skills)
    shutil.rmtree(skills / "delivery-refine")

    # When the launcher runs from it
    result = subprocess.run(  # noqa: S603
        [SH, str(skills / "delivery-orchestrator" / "scripts" / "launch-lanes.sh"), "--dry-run", "a-001"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    # Then it refuses, naming the missing skill
    assert result.returncode == 1
    assert "delivery-refine is not installed beside delivery-orchestrator" in result.stderr
