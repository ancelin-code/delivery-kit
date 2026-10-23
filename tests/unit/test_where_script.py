"""Behavioural tests for where.sh and install-routing.sh.

where.sh answers "where does the project stand, and what next" in one call, so
the tests pin the NEXT line it derives for each position a run can be in. Claims
are simulated as remote-tracking refs and pull request state through a fake gh,
so no network or forge is involved.
"""

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.conftest import SH

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents" / "skills" / "delivery-orchestrator" / "scripts"
WHERE = SCRIPTS / "where.sh"
INSTALL = SCRIPTS / "install-routing.sh"

OK = 0
ERROR = 1

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git is required",
)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603, S607


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


def write(repo: Path, path: str, text: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def artifact(repo: Path, path: str, status: str, extra: str = "") -> None:
    write(repo, path, f"# Title\n\n**Status:** {status}\n{extra}")


def task(repo: Path, task_id: str, depends_on: str = "", review: str | None = None, *, alone: bool = False) -> None:
    lenses = "" if review is None else f"review: [{review}]\n"
    write(
        repo,
        f"delivery/tasks/{task_id}.md",
        f"---\nid: {task_id}\ntitle: Do {task_id}\nepic: a\ndepends_on: [{depends_on}]\n"
        f"parallel: {str(not alone).lower()}\nconflicts_with: []\ntier: build\n{lenses}---\n\n"
        "## Acceptance criteria\n- observable\n",
    )


def approved_plan(repo: Path, run_as: str = "lanes") -> None:
    artifact(repo, "delivery/prd.md", "approved")
    artifact(repo, "delivery/decomposition.md", "approved", f"\n**Run as:** {run_as}\n")


def claim(repo: Path, task_id: str) -> None:
    git(repo, "update-ref", f"refs/remotes/origin/task/{task_id}", "HEAD")


class PullRequest(NamedTuple):
    """An open pull request out of draft, as the fake gh reports it."""

    number: int
    files: list[str] = []  # noqa: RUF012
    labels: list[str] = []  # noqa: RUF012


def fake_gh(
    tmp_path: Path,
    *,
    merged: list[str] = [],  # noqa: B006
    in_review: dict[str, PullRequest] = {},  # noqa: B006
    failing: bool = False,
) -> Path:
    bin_dir = tmp_path / "ghbin"
    bin_dir.mkdir(exist_ok=True)
    heads = " ".join(f"task/{task_id}" for task_id in merged)
    open_heads = " ".join(f"task/{task_id}" for task_id in in_review)
    # pr view answers with the lines where.sh's --jq filter would print.
    for task_id, pr in in_review.items():
        lines = [f"N\t{pr.number}"] + [f"L\t{name}" for name in pr.labels] + [f"F\t{path}" for path in pr.files]
        (bin_dir / f"view-task_{task_id}").write_text("\n".join(lines) + "\n", encoding="utf-8")
    body = (
        "exit 1\n"
        if failing
        else f"dir={shlex.quote(str(bin_dir))}\n"
        'if [[ "$1 $2" == "pr view" ]]; then cat "$dir/view-${3//\\//_}" || exit 1; exit 0; fi\n'
        'if [[ "$*" == *"--state open"* ]]; then\n'
        f"  for b in {shlex.join(open_heads.split())}; do printf '%s\\n' \"$b\"; done\n"
        "  exit 0\n"
        "fi\n"
        'head=""; args=("$@")\n'
        'for i in "${!args[@]}"; do [[ "${args[$i]}" != --head ]] || head="${args[$((i + 1))]}"; done\n'
        '[[ "$*" == *"--state merged"* ]] || exit 0\n'
        f"for b in {shlex.join(heads.split())}; do\n"
        '  [[ -n "$head" && "$b" != "$head" ]] || printf \'%s\\n\' "$b"\n'
        "done\n"
    )
    (bin_dir / "gh").write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def where(repo: Path, bin_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return subprocess.run(  # noqa: S603
        [SH, str(WHERE), "--no-fetch"],
        cwd=cwd or repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def rows(stdout: str, key: str) -> list[list[str]]:
    return [line.split("\t")[1:] for line in stdout.splitlines() if line.startswith(f"{key}\t")]


def actions(stdout: str) -> list[str]:
    return [row[0] for row in rows(stdout, "NEXT")]


class TestPhases:
    """Before lanes, the next action follows from which artifact is missing or unapproved."""

    def test_an_empty_project_starts_with_requirements(self, tmp_path: Path) -> None:
        # Given a repository with no delivery files
        repo = make_repo(tmp_path)

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then requirements are missing, and writing them is next
        assert result.returncode == OK
        assert ["requirements", "missing", "delivery/prd.md"] in rows(result.stdout, "PHASE")
        assert actions(result.stdout)[-1] == "write-requirements"

    def test_a_draft_prd_waits_for_approval(self, tmp_path: Path) -> None:
        # Given a draft PRD
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "draft")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then its approval is next
        assert actions(result.stdout)[-1] == "approve-requirements"

    def test_an_unfilled_template_status_is_not_approved(self, tmp_path: Path) -> None:
        # Given a PRD whose status is still the template's choice
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "draft | approved")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then it still awaits approval
        assert actions(result.stdout)[-1] == "approve-requirements"

    def test_a_draft_contract_holds_decomposition(self, tmp_path: Path) -> None:
        # Given an approved PRD and a draft contract
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")
        artifact(repo, "delivery/contracts/payload.md", "draft")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then the contract's approval is next, named
        assert rows(result.stdout, "NEXT")[-1] == ["approve-design", "awaiting approval: delivery/contracts/payload.md"]

    def test_a_proposed_decision_record_holds_decomposition(self, tmp_path: Path) -> None:
        # Given an approved PRD and a proposed decision record
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")
        artifact(repo, "docs/adr/ADR-001-x.md", "proposed")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then design approval is next
        assert actions(result.stdout)[-1] == "approve-design"

    def test_without_a_spine_the_choice_is_design_or_decompose(self, tmp_path: Path) -> None:
        # Given an approved PRD and no design documents
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then the choice between design and decomposition is next
        assert actions(result.stdout)[-1] == "design-or-decompose"

    def test_with_an_agreed_spine_the_next_phase_is_decomposition(self, tmp_path: Path) -> None:
        # Given an approved PRD and an agreed contract
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")
        artifact(repo, "delivery/contracts/payload.md", "agreed")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then decomposition is next
        assert actions(result.stdout)[-1] == "decompose"

    def test_a_draft_decomposition_waits_for_approval(self, tmp_path: Path) -> None:
        # Given a draft decomposition with a task
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")
        artifact(repo, "delivery/decomposition.md", "draft")
        task(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then its approval is next, and no task is reported yet
        assert actions(result.stdout)[-1] == "approve-decomposition"
        assert rows(result.stdout, "TASK") == []


class TestLanes:
    """Once decomposition is approved, the next action follows from derived task state."""

    def test_ready_tasks_are_launched(self, tmp_path: Path) -> None:
        # Given an approved plan with two ready tasks
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        task(repo, "a-002")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then starting both is next
        assert rows(result.stdout, "NEXT")[-1][0] == "start"
        assert "a-001 a-002" in rows(result.stdout, "NEXT")[-1][1]

    def test_a_serial_set_waits_for_the_task_in_flight(self, tmp_path: Path) -> None:
        # Given a serial plan with its first task claimed
        repo = make_repo(tmp_path)
        approved_plan(repo, run_as="serially")
        task(repo, "a-001", alone=True)
        task(repo, "a-002", alone=True)
        claim(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then it waits for that task before the next
        assert rows(result.stdout, "NEXT")[-1] == ["wait", "a-001 runs alone and is in flight; then a-002"]

    def test_a_serial_set_with_nothing_in_flight_starts_one_task(self, tmp_path: Path) -> None:
        # Given a serial plan with nothing claimed
        repo = make_repo(tmp_path)
        approved_plan(repo, run_as="serially")
        task(repo, "a-001", alone=True)
        task(repo, "a-002", alone=True)

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then only the first task is started
        action, detail = rows(result.stdout, "NEXT")[-1]
        assert action == "start"
        assert detail.startswith("alone, first of: a-001 a-002 (sh ")
        assert detail.endswith("launch-lanes.sh a-001)")

    def test_a_task_that_runs_alone_waits_for_work_in_flight(self, tmp_path: Path) -> None:
        # Given a task that runs alone, and another in flight
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        task(repo, "a-002", alone=True)
        claim(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then it waits for the work in flight to merge
        assert rows(result.stdout, "NEXT")[-1] == ["wait", "a-002 runs alone, after in-flight work merges: a-001"]

    def test_shared_tasks_go_first_and_the_lone_one_is_named(self, tmp_path: Path) -> None:
        # Given a ready task and one that runs alone
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        task(repo, "a-002", alone=True)

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then the shared task starts and the lone one is named for after
        action, detail = rows(result.stdout, "NEXT")[-1]
        assert action == "start"
        assert detail.startswith("launch lanes for: a-001 (sh ")
        assert detail.endswith("; after they merge, alone: a-002")

    def test_a_merged_task_with_its_branch_deleted_is_not_offered_again(self, tmp_path: Path) -> None:
        # Given a-001 merged and its branch deleted, and a-002 depending on it
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        task(repo, "a-002", depends_on="a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, merged=["a-001"]))

        # Then only a-002 is offered
        action, detail = rows(result.stdout, "NEXT")[-1]
        assert action == "start"
        assert detail.startswith("launch lanes for: a-002 (sh ")

    def test_every_task_merged_is_complete(self, tmp_path: Path) -> None:
        # Given the only task merged
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, merged=["a-001"]))

        # Then the project is complete
        assert actions(result.stdout)[-1] == "complete"

    def test_blocked_with_nothing_in_flight_is_reported_as_stuck(self, tmp_path: Path) -> None:
        """A dependency that nobody holds and that is not ready cannot arise, except by a cycle."""
        # Given two tasks that depend on each other
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001", depends_on="a-002")
        task(repo, "a-002", depends_on="a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then unblocking is next
        assert actions(result.stdout)[-1] == "unblock"

    def test_unreadable_pull_request_state_is_an_error_not_a_guess(self, tmp_path: Path) -> None:
        # Given gh fails
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, failing=True))

        # Then it errors rather than offering a start
        assert result.returncode == ERROR
        assert "NEXT\tstart" not in result.stdout


def milestone_plan(repo: Path, second_epics: str = "") -> None:
    """Two milestones; the first holds epic a, the one task() writes into."""
    artifact(repo, "delivery/prd.md", "approved")
    artifact(
        repo,
        "delivery/decomposition.md",
        "approved",
        "\n## Milestones\n\n### skeleton\n\n**Exit:** it works.\n**Requirements:**\n**Epics:** a\n\n"
        f"### team\n\n**Exit:** it is shared.\n**Requirements:**\n**Epics:** {second_epics}\n\n"
        "## Parallelism\n\n**Run as:** lanes\n",
    )


class TestMilestones:
    """With milestones, merged work stops at a review instead of reading as complete."""

    def test_the_current_milestone_runs_lanes_as_usual(self, tmp_path: Path) -> None:
        # Given two milestones, with a ready task in the first
        repo = make_repo(tmp_path)
        milestone_plan(repo)
        task(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then the first is active and its task starts
        assert rows(result.stdout, "MILESTONE") == [["skeleton", "active", "a", "-"], ["team", "planned", "-", "-"]]
        assert actions(result.stdout)[-1] == "start"

    def test_a_merged_milestone_asks_for_its_review(self, tmp_path: Path) -> None:
        # Given the first milestone's only task merged
        repo = make_repo(tmp_path)
        milestone_plan(repo)
        task(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, merged=["a-001"]))

        # Then its review is next, with the coverage command
        action, detail = rows(result.stdout, "NEXT")[-1]
        assert action == "review-milestone"
        assert "write delivery/milestones/skeleton.md with delivery-decompose" in detail
        assert detail.endswith("delivery-status/scripts/coverage.sh --milestone skeleton)")

    def test_a_draft_review_awaits_approval(self, tmp_path: Path) -> None:
        # Given a merged milestone with a draft review
        repo = make_repo(tmp_path)
        milestone_plan(repo)
        task(repo, "a-001")
        artifact(repo, "delivery/milestones/skeleton.md", "draft")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, merged=["a-001"]))

        # Then the review's approval is next
        assert rows(result.stdout, "NEXT")[-1] == [
            "approve-milestone-review",
            "delivery/milestones/skeleton.md awaits human approval",
        ]

    def test_an_approved_review_asks_for_the_next_cut(self, tmp_path: Path) -> None:
        # Given a merged milestone with an approved review
        repo = make_repo(tmp_path)
        milestone_plan(repo)
        task(repo, "a-001")
        artifact(repo, "delivery/milestones/skeleton.md", "approved")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, merged=["a-001"]))

        # Then cutting the next milestone is next
        assert actions(result.stdout)[-1] == "decompose-milestone"
        assert rows(result.stdout, "NEXT")[-1][1].startswith("team: ")

    def test_complete_once_the_last_review_is_approved(self, tmp_path: Path) -> None:
        # Given both milestones merged and only the first reviewed
        repo = make_repo(tmp_path)
        milestone_plan(repo, second_epics="b")
        task(repo, "a-001")
        write(
            repo,
            "delivery/tasks/b-001.md",
            "---\nid: b-001\ntitle: Do b-001\nepic: b\ndepends_on: []\nparallel: true\n"
            "conflicts_with: []\ntier: build\n---\n\n## Acceptance criteria\n- observable\n",
        )
        artifact(repo, "delivery/milestones/skeleton.md", "approved")
        merged = fake_gh(tmp_path, merged=["a-001", "b-001"])

        # When where.sh runs
        result = where(repo, merged)

        # Then the second milestone's review is next
        assert actions(result.stdout)[-1] == "review-milestone"

        # When that review is approved too
        artifact(repo, "delivery/milestones/team.md", "approved")
        result = where(repo, merged)

        # Then the project is complete
        assert actions(result.stdout)[-1] == "complete"

    def test_a_plan_without_milestones_still_completes(self, tmp_path: Path) -> None:
        # Given a plan without milestones, its task merged
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, merged=["a-001"]))

        # Then no milestone is reported and the project is complete
        assert rows(result.stdout, "MILESTONE") == []
        assert actions(result.stdout)[-1] == "complete"


def split_install(tmp_path: Path) -> Path:
    """The layout an update leaves after a copy install: delivery-implement was
    up to date, so it stayed a copy in .claude/skills while the other four were
    moved to .agents/skills and linked. Returns where.sh as Claude Code reaches it.
    """
    root = tmp_path / "install"
    canonical = root / ".agents" / "skills"
    linked = root / ".claude" / "skills"
    canonical.mkdir(parents=True)
    linked.mkdir(parents=True)
    for skill in SCRIPTS.parents[1].iterdir():
        if skill.name == "delivery-implement":
            shutil.copytree(skill, linked / skill.name)
        else:
            shutil.copytree(skill, canonical / skill.name)
            (linked / skill.name).symlink_to(Path("../../.agents/skills") / skill.name)
    return linked / "delivery-orchestrator" / "scripts" / "where.sh"


class TestInstallLayout:
    """The kit's skills find each other as siblings, so a split install is the first thing to fix."""

    def test_a_split_install_is_reported_before_anything_else(self, tmp_path: Path) -> None:
        # Given a ready task, and an install split between two skill directories
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        script = split_install(tmp_path)
        env = os.environ.copy()
        env["PATH"] = f"{fake_gh(tmp_path)}{os.pathsep}{env['PATH']}"

        # When where.sh runs from the split install
        result = subprocess.run(  # noqa: S603
            [SH, str(script), "--no-fetch"], cwd=repo, env=env, capture_output=True, text=True, check=False
        )

        # Then repairing the install is the only next action
        assert result.returncode == OK, result.stderr
        assert actions(result.stdout) == ["repair-install"]
        detail = rows(result.stdout, "NEXT")[0][1]
        assert ".agents/skills: delivery-implement." in detail
        assert rows(result.stdout, "PHASE") == []

    def test_a_missing_delivery_refine_is_reported(self, tmp_path: Path) -> None:
        # Given an install without delivery-refine
        repo = make_repo(tmp_path)
        skills = tmp_path / "skills"
        shutil.copytree(SCRIPTS.parents[1], skills)
        shutil.rmtree(skills / "delivery-refine")
        env = os.environ.copy()
        env["PATH"] = f"{fake_gh(tmp_path)}{os.pathsep}{env['PATH']}"

        # When where.sh runs from it
        result = subprocess.run(  # noqa: S603
            [SH, str(skills / "delivery-orchestrator" / "scripts" / "where.sh"), "--no-fetch"],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        # Then repairing the install is next, naming the missing skill
        assert actions(result.stdout) == ["repair-install"]
        assert rows(result.stdout, "NEXT")[0][1].endswith(
            ": delivery-refine. The kit installs whole: remove every delivery-* skill directory, "
            "then reinstall them all in one 'npx skills add', naming at least one agent that reads .agents/skills"
        )

    def test_a_whole_install_is_not_reported(self, tmp_path: Path) -> None:
        # Given the kit installed whole
        repo = make_repo(tmp_path)

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then no repair is asked for
        assert "repair-install" not in actions(result.stdout)


LENSES = """\
# lens     skill             paths that bring the lens in
general    code-review
security   security-review   */auth/* *.tf
docs       -                 *.md
"""


class TestReview:
    """Each pull request in review gets one REVIEW row per lens, naming the skill to run."""

    def test_without_a_lens_file_only_the_general_review_is_suggested(self, tmp_path: Path) -> None:
        # Given a pull request in review and no lens file
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, in_review={"a-001": PullRequest(7, ["src/app.py"])}))

        # Then only the general review is suggested
        assert result.returncode == OK
        assert rows(result.stdout, "REVIEW") == [["a-001", "#7", "general", "-", "default"]]
        assert ["review", "pull requests await review, one pass per REVIEW row: a-001"] in rows(result.stdout, "NEXT")

    def test_lenses_come_from_the_task_the_labels_and_the_paths(self, tmp_path: Path) -> None:
        # Given a lens file, a task asking for security, and pull requests with labels and paths
        repo = make_repo(tmp_path)
        approved_plan(repo)
        write(repo, "delivery/review-lenses.conf", LENSES)
        task(repo, "a-001", review="security")
        task(repo, "a-002")
        prs = {
            "a-001": PullRequest(7, ["src/auth/login.py"], ["ai-assisted"]),
            "a-002": PullRequest(8, ["infra/main.tf"], ["review:data"]),
        }

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, in_review=prs))

        # Then each lens is suggested with what brought it in
        assert rows(result.stdout, "REVIEW") == [
            ["a-001", "#7", "general", "code-review", "default"],
            ["a-001", "#7", "security", "security-review", "task,path:src/auth/login.py"],
            ["a-002", "#8", "general", "code-review", "default"],
            ["a-002", "#8", "data", "-", "label"],
            ["a-002", "#8", "security", "security-review", "path:infra/main.tf"],
        ]

    def test_a_pattern_is_matched_against_the_diff_not_expanded_in_the_checkout(self, tmp_path: Path) -> None:
        """README.md sits in the checkout; a globbed *.md would match only that and miss the diff."""
        # Given a lens on *.md and a pull request changing a nested markdown file
        repo = make_repo(tmp_path)
        approved_plan(repo)
        write(repo, "delivery/review-lenses.conf", LENSES)
        task(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path, in_review={"a-001": PullRequest(7, ["docs/guide/usage.md"])}))

        # Then the lens matches that file
        assert ["a-001", "#7", "docs", "-", "path:docs/guide/usage.md"] in rows(result.stdout, "REVIEW")

    def test_nothing_in_review_prints_no_review_rows(self, tmp_path: Path) -> None:
        # Given a lens file and nothing in review
        repo = make_repo(tmp_path)
        approved_plan(repo)
        write(repo, "delivery/review-lenses.conf", LENSES)
        task(repo, "a-001")

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then no review is suggested
        assert rows(result.stdout, "REVIEW") == []
        assert "review" not in actions(result.stdout)


class TestRouting:
    """The AGENTS.md block is what sends a project's requests to the orchestrator."""

    def test_a_missing_block_is_the_first_next_action(self, tmp_path: Path) -> None:
        # Given a repository without the routing block
        repo = make_repo(tmp_path)

        # When where.sh runs
        result = where(repo, fake_gh(tmp_path))

        # Then installing it is the first next action
        assert rows(result.stdout, "ROUTING") == [["missing"]]
        assert actions(result.stdout)[0] == "install-routing"
        assert "install-routing.sh" in rows(result.stdout, "NEXT")[0][1]

    def test_install_creates_agents_md_and_where_then_sees_it(self, tmp_path: Path) -> None:
        # Given a repository without AGENTS.md
        repo = make_repo(tmp_path)

        # When the routing is installed
        result = subprocess.run([SH, str(INSTALL)], cwd=repo, capture_output=True, text=True, check=False)  # noqa: S603

        # Then AGENTS.md and the lens file are added
        assert result.stdout == "ADDED\tAGENTS.md\nADDED\tdelivery/review-lenses.conf\n"
        assert "delivery-orchestrator" in (repo / "AGENTS.md").read_text(encoding="utf-8")

        # When where.sh runs afterwards
        after = where(repo, fake_gh(tmp_path))

        # Then it sees the routing and asks for nothing
        assert rows(after.stdout, "ROUTING") == [["present"]]
        assert "install-routing" not in actions(after.stdout)

    def test_install_appends_after_existing_content_once(self, tmp_path: Path) -> None:
        # Given an AGENTS.md with its own content
        repo = make_repo(tmp_path)
        (repo / "AGENTS.md").write_text("# Rules\n\nKeep it tidy.", encoding="utf-8")

        # When the routing is installed twice
        for _ in range(2):
            subprocess.run([SH, str(INSTALL)], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603

        # Then the block follows the content, once
        text = (repo / "AGENTS.md").read_text(encoding="utf-8")
        assert text.startswith("# Rules\n\nKeep it tidy.\n\n<!-- delivery-kit:routing -->\n")
        assert text.count("<!-- delivery-kit:routing -->") == 1

    def test_install_seeds_review_lenses_that_where_reads(self, tmp_path: Path) -> None:
        # Given the routing installed, with its seeded lens file
        repo = make_repo(tmp_path)
        subprocess.run([SH, str(INSTALL)], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603
        approved_plan(repo)
        task(repo, "a-001")

        # When where.sh runs with a pull request in review
        result = where(repo, fake_gh(tmp_path, in_review={"a-001": PullRequest(7, ["src/auth/login.py"])}))

        # Then the seeded lens file is read
        assert rows(result.stdout, "REVIEW") == [["a-001", "#7", "general", "-", "default"]]

    def test_install_leaves_an_edited_lens_file_alone(self, tmp_path: Path) -> None:
        # Given an edited lens file
        repo = make_repo(tmp_path)
        write(repo, "delivery/review-lenses.conf", LENSES)

        # When the routing is installed
        result = subprocess.run([SH, str(INSTALL)], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603

        # Then the lens file is reported present and left as it was
        assert "PRESENT\tdelivery/review-lenses.conf" in result.stdout
        assert (repo / "delivery/review-lenses.conf").read_text(encoding="utf-8") == LENSES

    @pytest.mark.parametrize("script", [WHERE, INSTALL])
    def test_refuses_to_run_below_the_repository_root(self, tmp_path: Path, script: Path) -> None:
        # Given a subdirectory of the repository
        repo = make_repo(tmp_path)
        (repo / "src").mkdir()
        env = os.environ.copy()
        env["PATH"] = f"{fake_gh(tmp_path)}{os.pathsep}{env['PATH']}"

        # When the script runs there
        result = subprocess.run(  # noqa: S603
            [SH, str(script)],
            cwd=repo / "src",
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        # Then it refuses, asking for the root
        assert result.returncode == ERROR
        assert "repository root" in result.stderr
