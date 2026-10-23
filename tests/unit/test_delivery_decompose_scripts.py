"""Behavioural tests for the delivery-decompose skill's validator.

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
SCRIPT = SKILLS / "delivery-decompose" / "scripts" / "validate-tasks.sh"

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
    covers: str | None = None,
) -> None:
    tasks_dir.mkdir(parents=True, exist_ok=True)
    body = "## Acceptance criteria\n- the thing is observably true\n" if criteria else "## Notes\n- none\n"
    if covers is not None:
        body = f"## Covers\n\n{covers}\n" + body
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


def write_summary(
    tasks_dir: Path, groups: dict[str, list[str]] | None = None, run_as: str = "lanes", milestones: str = ""
) -> Path:
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
        f"# Decomposition: test\n\n{milestones}## Epics\n\n{sections}## Parallelism\n\n**Run as:** {run_as}\n",
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
        # Given a serial set whose tasks all run alone
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", parallel="false")
        write_task(tasks, "ingestion-002", parallel="false")
        write_summary(tasks, run_as="serially")

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID

    def test_rejects_a_serial_set_with_a_task_that_would_run_alongside(self, tmp_path: Path) -> None:
        """The summary says one at a time; the launcher would start two."""
        # Given a serial set with one task that may run alongside
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", parallel="false")
        write_task(tasks, "ingestion-002")
        write_summary(tasks, run_as="serially")

        # When the task set is validated
        result = validate(tasks)

        # Then that task is rejected
        assert result.returncode == INVALID
        assert "ingestion-002" in result.stdout
        assert "parallel must be false" in result.stdout

    def test_rejects_lanes_when_every_task_runs_alone(self, tmp_path: Path) -> None:
        # Given a lanes set where every task runs alone
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", parallel="false")
        write_task(tasks, "ingestion-002", parallel="false")
        write_summary(tasks, run_as="lanes")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected as serial
        assert result.returncode == INVALID
        assert "should say serially" in result.stdout

    def test_accepts_lanes_with_one_task_that_runs_alone(self, tmp_path: Path) -> None:
        """A migration or lockfile change can run alone inside a set that otherwise parallelizes."""
        # Given a lanes set with one task that runs alone
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", parallel="false")
        write_task(tasks, "ingestion-002")
        write_summary(tasks, run_as="lanes")

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID

    def test_rejects_an_undecided_run_as(self, tmp_path: Path) -> None:
        # Given a summary whose Run as is still the template's choice
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_summary(tasks, run_as="lanes | serially")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "pick one" in result.stdout


class TestValidTaskSets:
    def test_accepts_a_linear_dependency_chain(self, tmp_path: Path) -> None:
        # Given a task depending on another
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_task(tasks, "ingestion-002", depends_on="ingestion-001")

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID
        assert "RESULT\tvalid" in result.stdout

    def test_reports_task_and_epic_counts(self, tmp_path: Path) -> None:
        # Given two tasks in two epics
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_task(tasks, "api-001", epic="api")

        # When the task set is validated
        result = validate(tasks)

        # Then both counts are reported
        assert "TASKS\t2" in result.stdout
        assert "EPICS\t2" in result.stdout


class TestRejectedTaskSets:
    """Each case here would stall one or more lanes if it reached a developer."""

    def test_rejects_a_dependency_that_does_not_exist(self, tmp_path: Path) -> None:
        # Given a dependency on a task that does not exist
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", depends_on="ingestion-404")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "unknown task" in result.stdout

    def test_rejects_a_dependency_cycle(self, tmp_path: Path) -> None:
        """A cycle leaves every task in it permanently blocked."""
        # Given two tasks depending on each other
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", depends_on="ingestion-002")
        write_task(tasks, "ingestion-002", depends_on="ingestion-001")

        # When the task set is validated
        result = validate(tasks)

        # Then the cycle is rejected
        assert result.returncode == INVALID
        assert "dependency cycle" in result.stdout

    def test_rejects_a_task_depending_on_itself(self, tmp_path: Path) -> None:
        # Given a task depending on itself
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", depends_on="ingestion-001")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID

    def test_rejects_an_id_that_does_not_match_the_filename(self, tmp_path: Path) -> None:
        """The filename is how every other tool finds the task."""
        # Given a task whose id is not its filename
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", file_name="ingestion-002")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "does not match the filename" in result.stdout

    @pytest.mark.parametrize("tier", TIERS)
    def test_accepts_every_documented_tier(self, tmp_path: Path, tier: str) -> None:
        """The validator and the conventions table have to agree.

        The tiers come from the conventions, so adding one there without
        teaching the validator fails here rather than at decomposition, after
        the epic has already been written.
        """
        # Given a task on a tier the conventions document
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", tier=tier)

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID, result.stdout

    def test_rejects_an_unknown_type(self, tmp_path: Path) -> None:
        """The type prefixes the lane's commit, so a typo reaches the history."""
        # Given a task with a type that is not conventional
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", task_type="feature")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "unknown type" in result.stdout

    def test_accepts_a_conventional_type(self, tmp_path: Path) -> None:
        # Given a fix task
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", task_type="fix")

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID

    @pytest.mark.parametrize("tier", ["gpt4", "Build"])
    def test_rejects_an_unknown_tier(self, tmp_path: Path, tier: str) -> None:
        # Given a task on an undocumented tier
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", tier=tier)

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected, listing the tiers
        assert result.returncode == INVALID
        assert f"unknown tier: '{tier}' (expected plan, build, or chore)" in result.stdout

    def test_rejects_a_task_with_no_tier(self, tmp_path: Path) -> None:
        # Given a task with no tier
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", tier=None)

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "missing required field: tier" in result.stdout

    def test_rejects_a_task_without_acceptance_criteria(self, tmp_path: Path) -> None:
        """Without criteria there is nothing to check the work against."""
        # Given a task without acceptance criteria
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", criteria=False)

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "Acceptance criteria" in result.stdout

    def test_accepts_an_epic_of_any_size(self, tmp_path: Path) -> None:
        """No count caps an epic: its size is the decomposer's judgement."""
        # Given an epic of 25 tasks
        tasks = tmp_path / "tasks"
        for n in range(1, 26):
            write_task(tasks, f"ingestion-{n:03d}")

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID

    def test_rejects_a_file_without_frontmatter(self, tmp_path: Path) -> None:
        # Given a task file without frontmatter
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tasks / "ingestion-001.md").write_text("# Just a heading\n", encoding="utf-8")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "no frontmatter" in result.stdout

    def test_rejects_a_conflict_with_an_unknown_task(self, tmp_path: Path) -> None:
        # Given a conflict with a task that does not exist
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", conflicts_with="ingestion-404")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID


class TestValidatorUsage:
    def test_dies_on_a_missing_tasks_directory(self, tmp_path: Path) -> None:
        # When the task set is validated
        result = validate(tmp_path / "absent")

        # Then it is a usage error
        assert result.returncode == USAGE_ERROR

    def test_dies_when_the_directory_holds_no_tasks(self, tmp_path: Path) -> None:
        # Given an empty tasks directory
        empty = tmp_path / "tasks"
        empty.mkdir()

        # When the task set is validated
        result = validate(empty)

        # Then it is a usage error
        assert result.returncode == USAGE_ERROR


class TestDecompositionSummary:
    """The summary carries the reasoning behind the cut, so it has to match it.

    Task files say what the work is; the summary says why it was grouped that
    way and where it serializes. A summary that has drifted from the task set
    is worse than none, because the approval gate reads it as current.
    """

    def test_rejects_a_task_set_with_no_summary(self, tmp_path: Path) -> None:
        """Decomposition is the phase; the summary is its artifact."""
        # Given a task set with no decomposition summary
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")

        # When the task set is validated
        result = validate(tasks, "--decomposition", str(tmp_path / "absent.md"))

        # Then it is rejected
        assert result.returncode == INVALID
        assert "no decomposition summary" in result.stdout

    def test_rejects_a_task_missing_from_the_summary(self, tmp_path: Path) -> None:
        """A launcher would run it anyway, so nobody approved that lane."""
        # Given a summary that omits one task
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_task(tasks, "ingestion-002")
        write_summary(tasks, {"ingestion": ["ingestion-001"]})

        # When the task set is validated
        result = validate(tasks)

        # Then that task is rejected
        assert result.returncode == INVALID
        assert "ingestion-002\tmissing from decomposition.md" in result.stdout

    def test_rejects_a_summary_listing_a_task_with_no_file(self, tmp_path: Path) -> None:
        """The lane can never start: there is nothing to launch it from."""
        # Given a summary listing a task with no file
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_summary(tasks, {"ingestion": ["ingestion-001", "ingestion-404"]})

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "lists a task with no file: 'ingestion-404'" in result.stdout

    def test_rejects_a_task_grouped_under_a_different_epic(self, tmp_path: Path) -> None:
        """The epic bounds the cap and names the slice, so the two must agree."""
        # Given a summary grouping a task under another epic
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001", epic="ingestion")
        write_summary(tasks, {"api": ["ingestion-001"]})

        # When the task set is validated
        result = validate(tasks)

        # Then the mismatch is rejected
        assert result.returncode == INVALID
        assert "'ingestion' in the task file, 'api' in decomposition.md" in result.stdout

    def test_ignores_task_ids_outside_the_epics_section(self, tmp_path: Path) -> None:
        """Only the Epics section declares membership.

        The critical path names the same ids in prose. Reading those as
        declarations would let a task drop out of Epics unnoticed.
        """
        # Given a summary naming an unknown id outside its Epics section
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

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID, result.stdout

    def test_accepts_a_summary_that_matches(self, tmp_path: Path) -> None:
        # Given a summary matching the task set
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")
        write_task(tasks, "api-001", epic="api")
        write_summary(tasks)

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID, result.stdout


PRD = """\
# Project

**Status:** approved

## Outcomes

- **A1.** One server serves one organisation.
- **A4.** Members sign in; revoking access takes effect at their next
  request.
- **X1a.** A member never reaches a store they were not granted.

## Invariants

- Plain files are the source of truth.
"""


def write_prd(tasks_dir: Path) -> None:
    (tasks_dir.parent / "prd.md").write_text(PRD, encoding="utf-8")


def milestone(slug: str, *, epics: str = "", targets: str = "", exit_line: bool = True) -> str:
    exit_text = "**Exit:** it works end to end.\n" if exit_line else ""
    return f"### {slug}\n\nWhy this slice first.\n\n{exit_text}**Requirements:** {targets}\n**Epics:** {epics}\n\n"


def plan(*milestones: str) -> str:
    return "## Milestones\n\n" + "".join(milestones)


def review_note(tasks_dir: Path, slug: str, status: str) -> None:
    folder = tasks_dir.parent / "milestones"
    folder.mkdir(exist_ok=True)
    (folder / f"{slug}.md").write_text(f"# Milestone review: {slug}\n\n**Status:** {status}\n", encoding="utf-8")


def failures(result: subprocess.CompletedProcess[str]) -> list[list[str]]:
    return [line.split("\t")[1:] for line in result.stdout.splitlines() if line.startswith("FAIL\t")]


class TestCovers:
    """A task names the requirements it covers, so what is left of each can be derived."""

    def test_accepts_full_and_partial_covers_of_known_requirements(self, tmp_path: Path) -> None:
        # Given a task covering one requirement whole and one in part
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "ingestion-001", covers="- A1\n- A4 (part): sign-in only;\n  revocation comes later")

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID

    def test_rejects_an_id_the_requirements_do_not_define(self, tmp_path: Path) -> None:
        # Given a task covering an undefined requirement
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "ingestion-001", covers="- A9")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected, naming the PRD
        assert result.returncode == INVALID
        assert failures(result) == [
            ["ingestion-001", "covers 'A9', which is no requirement id in " + str(tmp_path / "prd.md")]
        ]

    def test_rejects_a_partial_cover_without_a_note(self, tmp_path: Path) -> None:
        # Given a partial cover with no note
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "ingestion-001", covers="- A4 (part):")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "covers A4 in part with no note" in failures(result)[0][1]

    def test_rejects_a_line_it_cannot_read(self, tmp_path: Path) -> None:
        # Given a Covers line in no known form
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "ingestion-001", covers="- A4 partly, sign-in")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "unreadable Covers line 'A4 partly, sign-in'" in failures(result)[0][1]

    def test_rejects_covers_when_the_requirements_have_no_ids(self, tmp_path: Path) -> None:
        # Given a task covering a requirement in a PRD without ids
        tasks = tmp_path / "tasks"
        tasks.mkdir()
        (tmp_path / "prd.md").write_text("# P\n\n## Outcomes\n\n- one server\n", encoding="utf-8")
        write_task(tasks, "ingestion-001", covers="- A1")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert "has no ids" in failures(result)[0][1]

    def test_a_set_without_covers_needs_no_requirements(self, tmp_path: Path) -> None:
        """Covers are optional: the check costs nothing to a project that does not use them."""
        # Given a task set without covers and no PRD
        tasks = tmp_path / "tasks"
        write_task(tasks, "ingestion-001")

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID


class TestMilestones:
    """Only the current milestone is cut, and its cut covers what it targets."""

    def setup_two_milestones(
        self, tasks: Path, *, second_epics: str = "", covers: str = "- A1\n- A4 (part): sign-in"
    ) -> None:
        write_prd(tasks)
        write_task(tasks, "server-001", epic="server", covers=covers)
        write_summary(
            tasks,
            milestones=plan(
                milestone("skeleton", epics="server", targets="A1, A4 (part)"),
                milestone("team", epics=second_epics, targets="A4, X1a"),
            ),
        )

    def test_accepts_a_cut_of_the_current_milestone(self, tmp_path: Path) -> None:
        # Given two milestones, with the first cut and fully covered
        tasks = tmp_path / "tasks"
        self.setup_two_milestones(tasks)

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid, and the first is current
        assert result.returncode == VALID, result.stdout
        assert "MILESTONES\t2\tcurrent=skeleton" in result.stdout

    def test_rejects_a_target_no_task_of_the_milestone_covers(self, tmp_path: Path) -> None:
        # Given a milestone target no task covers
        tasks = tmp_path / "tasks"
        self.setup_two_milestones(tasks, covers="- A1")

        # When the task set is validated
        result = validate(tasks)

        # Then the milestone is rejected
        assert result.returncode == INVALID
        assert failures(result) == [["skeleton", "targets A4, but no task of the milestone covers it"]]

    def test_rejects_tasks_of_a_milestone_after_the_current_one(self, tmp_path: Path) -> None:
        # Given tasks cut for the second milestone before the first is reviewed
        tasks = tmp_path / "tasks"
        self.setup_two_milestones(tasks, second_epics="team")
        write_task(tasks, "team-001", epic="team", covers="- A4\n- X1a")
        write_summary(
            tasks,
            milestones=plan(
                milestone("skeleton", epics="server", targets="A1, A4 (part)"),
                milestone("team", epics="team", targets="A4, X1a"),
            ),
        )

        # When the task set is validated
        result = validate(tasks)

        # Then they are rejected
        assert result.returncode == INVALID
        assert failures(result) == [
            [
                "team-001",
                (
                    "belongs to milestone team, after the current one, skeleton: "
                    "cut it once skeleton's review note is approved"
                ),
            ]
        ]

    def test_an_approved_review_makes_the_next_milestone_current(self, tmp_path: Path) -> None:
        # Given the first milestone's review approved, and the second cut
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "server-001", epic="server", covers="- A1\n- A4 (part): sign-in")
        write_task(tasks, "team-001", epic="team", covers="- A4\n- X1a", parallel="false")
        write_summary(
            tasks,
            milestones=plan(
                milestone("skeleton", epics="server", targets="A1, A4 (part)"),
                milestone("team", epics="team", targets="A4, X1a"),
            ),
            run_as="serially",
        )
        review_note(tasks, "skeleton", "approved")

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid, and the second is current
        assert result.returncode == VALID, result.stdout
        assert "current=team" in result.stdout

    def test_a_draft_review_does_not_close_a_milestone(self, tmp_path: Path) -> None:
        # Given the second milestone cut while the first's review is a draft
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "server-001", epic="server", covers="- A1\n- A4 (part): sign-in")
        write_task(tasks, "team-001", epic="team", covers="- A4\n- X1a")
        write_summary(
            tasks,
            milestones=plan(
                milestone("skeleton", epics="server", targets="A1, A4 (part)"),
                milestone("team", epics="team", targets="A4, X1a"),
            ),
        )
        review_note(tasks, "skeleton", "draft")

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID

    def test_run_as_describes_the_current_milestone_only(self, tmp_path: Path) -> None:
        """A closed milestone that ran in lanes does not stop the next from running serially."""
        # Given a closed milestone in lanes, and a serial current one
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "server-001", epic="server", covers="- A1")
        write_task(tasks, "server-002", epic="server", covers="- A4 (part): sign-in")
        write_task(tasks, "team-001", epic="team", covers="- A4", parallel="false")
        write_task(tasks, "team-002", epic="team", covers="- X1a", parallel="false")
        write_summary(
            tasks,
            milestones=plan(
                milestone("skeleton", epics="server", targets="A1, A4 (part)"),
                milestone("team", epics="team", targets="A4, X1a"),
            ),
            run_as="serially",
        )
        review_note(tasks, "skeleton", "approved")

        # When the task set is validated
        result = validate(tasks)

        # Then it is valid
        assert result.returncode == VALID

    def test_rejects_an_epic_in_no_milestone(self, tmp_path: Path) -> None:
        # Given an epic no milestone lists
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "server-001", epic="server", covers="- A1")
        write_task(tasks, "ops-001", epic="ops")
        write_summary(tasks, milestones=plan(milestone("skeleton", epics="server", targets="A1")))

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert ["ops", "epic belongs to no milestone: list it on a milestone's **Epics:** line"] in failures(result)

    def test_rejects_an_epic_in_two_milestones(self, tmp_path: Path) -> None:
        # Given an epic listed by two milestones
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "server-001", epic="server", covers="- A1")
        write_summary(
            tasks,
            milestones=plan(milestone("skeleton", epics="server", targets="A1"), milestone("team", epics="server")),
        )

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert ["server", "epic is in two milestones: skeleton and team"] in failures(result)

    def test_rejects_a_milestone_without_an_exit_criterion(self, tmp_path: Path) -> None:
        # Given a milestone without an Exit line
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "server-001", epic="server", covers="- A1")
        write_summary(tasks, milestones=plan(milestone("skeleton", epics="server", targets="A1", exit_line=False)))

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert result.returncode == INVALID
        assert failures(result)[0][0] == "skeleton"
        assert "no '**Exit:**' line" in failures(result)[0][1]

    def test_rejects_a_target_the_requirements_do_not_define(self, tmp_path: Path) -> None:
        # Given a milestone targeting an undefined requirement
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "server-001", epic="server", covers="- A1")
        write_summary(
            tasks,
            milestones=plan(milestone("skeleton", epics="server", targets="A1"), milestone("later", targets="Z9")),
        )

        # When the task set is validated
        result = validate(tasks)

        # Then it is rejected
        assert failures(result) == [
            ["later", "targets 'Z9', which is no requirement id in " + str(tmp_path / "prd.md")]
        ]

    def test_a_wrapped_requirements_line_is_read_whole(self, tmp_path: Path) -> None:
        # Given a Requirements line wrapped onto two lines
        tasks = tmp_path / "tasks"
        write_prd(tasks)
        write_task(tasks, "server-001", epic="server", covers="- A1")
        write_summary(
            tasks,
            milestones=(
                "## Milestones\n\n### skeleton\n\n**Exit:** works.\n**Requirements:** A1,\n  X1a\n**Epics:** server\n\n"
            ),
        )

        # When the task set is validated
        result = validate(tasks)

        # Then the target on the second line is checked too
        assert failures(result) == [["skeleton", "targets X1a, but no task of the milestone covers it"]]
