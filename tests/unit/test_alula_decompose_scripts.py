"""Behavioural tests for the alula-decompose skill's validator.

``validate-tasks.sh`` is the gate between an approved decomposition and the
lanes that build on it, so the tests focus on the task sets it must reject: the
ones whose cost is paid later by several developers at once.
"""

import re
import subprocess
from pathlib import Path

import pytest

from tests.conftest import SH
from tests.unit.tiers import TIERS

SKILLS = Path(__file__).resolve().parents[2] / ".agents" / "skills"
SCRIPT = SKILLS / "alula-decompose" / "scripts" / "validate-tasks.sh"

VALID = 0
USAGE_ERROR = 1
INVALID = 2


def write_task(
    tasks_dir: Path,
    task_id: str,
    *,
    epic: str = "ingestion",
    depends_on: str = "",
    conflicts_with: str = "",
    tier: str | None = "build",
    task_type: str | None = None,
    parallel: str = "true",
    criteria: bool = True,
    file_name: str | None = None,
) -> None:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    body = "## Acceptance criteria\n- the thing is observably true\n" if criteria else "## Notes\n- none\n"
    (tasks_dir / f"{file_name or task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\n"
        f"title: Do {task_id}\n"
        f"epic: {epic}\n"
        f"depends_on: [{depends_on}]\n"
        f"parallel: {parallel}\n"
        f"conflicts_with: [{conflicts_with}]\n"
        f"{'' if tier is None else f'tier: {tier}\n'}"
        f"{'' if task_type is None else f'type: {task_type}\n'}"
        "---\n\n" + body,
        encoding="utf-8",
    )


def write_summary(tasks_dir: Path, groups: dict[str, list[str]] | None = None, run_as: str = "lanes") -> Path:
    """Write the decomposition summary the validator cross-checks.

    With no ``groups`` it mirrors whatever the task files say, which is what
    most tests want: they exercise some other check and need the summary
    merely to agree. Pass ``groups`` to make it disagree on purpose.
    """
    if groups is None:
        groups = {}
        for task in sorted(tasks_dir.glob("*.md")):
            front = task.read_text(encoding="utf-8")
            task_id = re.search(r"^id:[ \t]*(\S+)[ \t]*$", front, re.MULTILINE)
            epic = re.search(r"^epic:[ \t]*(\S+)[ \t]*$", front, re.MULTILINE)
            if task_id is not None and epic is not None:
                groups.setdefault(epic.group(1), []).append(task_id.group(1))

    sections = ""
    for epic, task_ids in groups.items():
        listed = "".join(f"- `{task_id}` - Do {task_id}\n" for task_id in task_ids)
        sections += f"### {epic}\n\nWhat the slice delivers.\n\n{listed}\n"

    path = tasks_dir.parent / "decomposition.md"
    path.write_text(
        f"# Decomposition: test\n\n## Epics\n\n{sections}## Parallelism\n\n**Run as:** {run_as}\n",
        encoding="utf-8",
    )
    return path


def validate(tasks_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # The summary is required, so write an agreeing one unless the test wrote
    # its own. Without this every test would assert on two failures: its own,
    # and a missing summary it never meant to exercise.
    if not (tasks_dir.parent / "decomposition.md").exists():
        write_summary(tasks_dir)
    return subprocess.run(  # noqa: S603
        [SH, str(SCRIPT), "--tasks-dir", str(tasks_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


class TestRunAs:
    """The launcher reads the fields; the summary is what a human approved."""

    def test_accepts_a_serial_set_whose_tasks_all_run_alone(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", parallel="false")
        write_task(tasks, "ingestion-002", parallel="false")
        write_summary(tasks, run_as="serially")
        assert validate(tasks).returncode == VALID

    def test_rejects_a_serial_set_with_a_task_that_would_run_alongside(self, tmp_path: Path) -> None:
        """The summary says one at a time; the launcher would start two."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", parallel="false")
        write_task(tasks, "ingestion-002")
        write_summary(tasks, run_as="serially")
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "ingestion-002" in result.stdout
        assert "parallel must be false" in result.stdout

    def test_rejects_lanes_when_every_task_runs_alone(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", parallel="false")
        write_task(tasks, "ingestion-002", parallel="false")
        write_summary(tasks, run_as="lanes")
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "should say serially" in result.stdout

    def test_accepts_lanes_with_one_task_that_runs_alone(self, tmp_path: Path) -> None:
        """A migration or lockfile change can run alone inside a set that otherwise parallelizes."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", parallel="false")
        write_task(tasks, "ingestion-002")
        write_summary(tasks, run_as="lanes")
        assert validate(tasks).returncode == VALID

    def test_rejects_an_undecided_run_as(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_summary(tasks, run_as="lanes | serially")
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "pick one" in result.stdout


class TestValidTaskSets:
    def test_accepts_a_linear_dependency_chain(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_task(tasks, "ingestion-002", depends_on="ingestion-001")
        result = validate(tasks)
        assert result.returncode == VALID
        assert "RESULT\tvalid" in result.stdout

    def test_reports_task_and_epic_counts(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_task(tasks, "api-001", epic="api")
        result = validate(tasks)
        assert "TASKS\t2" in result.stdout
        assert "EPICS\t2" in result.stdout


class TestRejectedTaskSets:
    """Each case here would stall one or more lanes if it reached a developer."""

    def test_rejects_a_dependency_that_does_not_exist(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", depends_on="ingestion-404")
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "unknown task" in result.stdout

    def test_rejects_a_dependency_cycle(self, tmp_path: Path) -> None:
        """A cycle leaves every task in it permanently blocked."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", depends_on="ingestion-002")
        write_task(tasks, "ingestion-002", depends_on="ingestion-001")
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "dependency cycle" in result.stdout

    def test_rejects_a_task_depending_on_itself(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", depends_on="ingestion-001")
        result = validate(tasks)
        assert result.returncode == INVALID

    def test_rejects_an_id_that_does_not_match_the_filename(self, tmp_path: Path) -> None:
        """The filename is how every other tool finds the task."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", file_name="ingestion-002")
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "does not match the filename" in result.stdout

    @pytest.mark.parametrize("tier", TIERS)
    def test_accepts_every_documented_tier(self, tmp_path: Path, tier: str) -> None:
        """The validator and the conventions table have to agree.

        The tiers come from the conventions, so adding one there without
        teaching the validator fails here rather than at decomposition, after
        the epic has already been written.
        """
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", tier=tier)
        result = validate(tasks)
        assert result.returncode == VALID, result.stdout

    def test_rejects_an_unknown_type(self, tmp_path: Path) -> None:
        """The type prefixes the lane's commit, so a typo reaches the history."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", task_type="feature")
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "unknown type" in result.stdout

    def test_accepts_a_conventional_type(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", task_type="fix")
        assert validate(tasks).returncode == VALID

    @pytest.mark.parametrize("tier", ["gpt4", "Build"])
    def test_rejects_an_unknown_tier(self, tmp_path: Path, tier: str) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", tier=tier)
        result = validate(tasks)
        assert result.returncode == INVALID
        assert f"unknown tier: '{tier}' (expected plan, build, or chore)" in result.stdout

    def test_rejects_a_task_with_no_tier(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", tier=None)
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "missing required field: tier" in result.stdout

    def test_rejects_a_task_without_acceptance_criteria(self, tmp_path: Path) -> None:
        """Without criteria there is nothing to check the work against."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", criteria=False)
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "Acceptance criteria" in result.stdout

    def test_rejects_an_epic_over_the_cap(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        for n in range(1, 12):
            write_task(tasks, f"ingestion-{n:03d}")
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "more than the 10 allowed" in result.stdout

    def test_the_epic_cap_is_configurable(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        for n in range(1, 12):
            write_task(tasks, f"ingestion-{n:03d}")
        assert validate(tasks, "--max-per-epic", "20").returncode == VALID

    def test_rejects_a_file_without_frontmatter(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tasks / "ingestion-001.md").write_text("# Just a heading\n", encoding="utf-8")
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "no frontmatter" in result.stdout

    def test_rejects_a_conflict_with_an_unknown_task(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", conflicts_with="ingestion-404")
        result = validate(tasks)
        assert result.returncode == INVALID


class TestValidatorUsage:
    def test_dies_on_a_missing_tasks_directory(self, tmp_path: Path) -> None:
        result = validate(tmp_path / "absent")
        assert result.returncode == USAGE_ERROR

    def test_dies_when_the_directory_holds_no_tasks(self, tmp_path: Path) -> None:
        empty = tmp_path / "tasks"
        empty.mkdir()
        result = validate(empty)
        assert result.returncode == USAGE_ERROR


class TestDecompositionSummary:
    """The summary carries the reasoning behind the cut, so it has to match it.

    Task files say what the work is; the summary says why it was grouped that
    way and where it serializes. A summary that has drifted from the task set
    is worse than none, because the approval gate reads it as current.
    """

    def test_rejects_a_task_set_with_no_summary(self, tmp_path: Path) -> None:
        """Decomposition is the phase; the summary is its artifact."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        result = validate(tasks, "--decomposition", str(tmp_path / "absent.md"))
        assert result.returncode == INVALID
        assert "no decomposition summary" in result.stdout

    def test_rejects_a_task_missing_from_the_summary(self, tmp_path: Path) -> None:
        """A launcher would run it anyway, so nobody approved that lane."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_task(tasks, "ingestion-002")
        write_summary(tasks, {"ingestion": ["ingestion-001"]})
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "ingestion-002\tmissing from decomposition.md" in result.stdout

    def test_rejects_a_summary_listing_a_task_with_no_file(self, tmp_path: Path) -> None:
        """The lane can never start: there is nothing to launch it from."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_summary(tasks, {"ingestion": ["ingestion-001", "ingestion-404"]})
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "lists a task with no file: 'ingestion-404'" in result.stdout

    def test_rejects_a_task_grouped_under_a_different_epic(self, tmp_path: Path) -> None:
        """The epic bounds the cap and names the slice, so the two must agree."""
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", epic="ingestion")
        write_summary(tasks, {"api": ["ingestion-001"]})
        result = validate(tasks)
        assert result.returncode == INVALID
        assert "'ingestion' in the task file, 'api' in decomposition.md" in result.stdout

    def test_ignores_task_ids_outside_the_epics_section(self, tmp_path: Path) -> None:
        """Only the Epics section declares membership.

        The critical path names the same ids in prose. Reading those as
        declarations would let a task drop out of Epics unnoticed.
        """
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        (tmp_path / "decomposition.md").write_text(
            "# Decomposition: test\n\n"
            "## Epics\n\n### ingestion\n\nWhat it delivers.\n\n"
            "- `ingestion-001` - Do ingestion-001\n\n"
            "## Parallelism\n\n**Run as:** lanes\n\n"
            "## Critical path\n\n- `ingestion-404` - not a declaration\n",
            encoding="utf-8",
        )
        result = validate(tasks)
        assert result.returncode == VALID, result.stdout

    def test_accepts_a_summary_that_matches(self, tmp_path: Path) -> None:
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_task(tasks, "api-001", epic="api")
        write_summary(tasks)
        result = validate(tasks)
        assert result.returncode == VALID, result.stdout
