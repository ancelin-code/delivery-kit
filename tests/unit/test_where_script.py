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

SCRIPTS = Path(__file__).resolve().parents[2] / ".agents" / "skills" / "alula" / "scripts"
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
        repo = make_repo(tmp_path)
        result = where(repo, fake_gh(tmp_path))
        assert result.returncode == OK
        assert ["requirements", "missing", "delivery/prd.md"] in rows(result.stdout, "PHASE")
        assert actions(result.stdout)[-1] == "write-requirements"

    def test_a_draft_prd_waits_for_approval(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "draft")
        assert actions(where(repo, fake_gh(tmp_path)).stdout)[-1] == "approve-requirements"

    def test_an_unfilled_template_status_is_not_approved(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "draft | approved")
        assert actions(where(repo, fake_gh(tmp_path)).stdout)[-1] == "approve-requirements"

    def test_a_draft_contract_holds_decomposition(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")
        artifact(repo, "delivery/contracts/payload.md", "draft")
        result = where(repo, fake_gh(tmp_path))
        assert rows(result.stdout, "NEXT")[-1] == ["approve-design", "awaiting approval: delivery/contracts/payload.md"]

    def test_a_proposed_decision_record_holds_decomposition(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")
        artifact(repo, "docs/adr/ADR-001-x.md", "proposed")
        assert actions(where(repo, fake_gh(tmp_path)).stdout)[-1] == "approve-design"

    def test_without_a_spine_the_choice_is_design_or_decompose(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")
        assert actions(where(repo, fake_gh(tmp_path)).stdout)[-1] == "design-or-decompose"

    def test_with_an_agreed_spine_the_next_phase_is_decomposition(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")
        artifact(repo, "delivery/contracts/payload.md", "agreed")
        assert actions(where(repo, fake_gh(tmp_path)).stdout)[-1] == "decompose"

    def test_a_draft_decomposition_waits_for_approval(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        artifact(repo, "delivery/prd.md", "approved")
        artifact(repo, "delivery/decomposition.md", "draft")
        task(repo, "a-001")
        result = where(repo, fake_gh(tmp_path))
        assert actions(result.stdout)[-1] == "approve-decomposition"
        assert rows(result.stdout, "TASK") == []


class TestLanes:
    """Once decomposition is approved, the next action follows from derived task state."""

    def test_ready_tasks_are_launched(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        task(repo, "a-002")
        result = where(repo, fake_gh(tmp_path))
        assert rows(result.stdout, "NEXT")[-1][0] == "start"
        assert "a-001 a-002" in rows(result.stdout, "NEXT")[-1][1]

    def test_a_serial_set_waits_for_the_task_in_flight(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo, run_as="serially")
        task(repo, "a-001", alone=True)
        task(repo, "a-002", alone=True)
        claim(repo, "a-001")
        result = where(repo, fake_gh(tmp_path))
        assert rows(result.stdout, "NEXT")[-1] == ["wait", "a-001 runs alone and is in flight; then a-002"]

    def test_a_serial_set_with_nothing_in_flight_starts_one_task(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo, run_as="serially")
        task(repo, "a-001", alone=True)
        task(repo, "a-002", alone=True)
        result = where(repo, fake_gh(tmp_path))
        action, detail = rows(result.stdout, "NEXT")[-1]
        assert action == "start"
        assert detail.startswith("alone, first of: a-001 a-002 (sh ")
        assert detail.endswith("launch-lanes.sh a-001)")

    def test_a_task_that_runs_alone_waits_for_work_in_flight(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        task(repo, "a-002", alone=True)
        claim(repo, "a-001")
        result = where(repo, fake_gh(tmp_path))
        assert rows(result.stdout, "NEXT")[-1] == ["wait", "a-002 runs alone, after in-flight work merges: a-001"]

    def test_shared_tasks_go_first_and_the_lone_one_is_named(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        task(repo, "a-002", alone=True)
        result = where(repo, fake_gh(tmp_path))
        action, detail = rows(result.stdout, "NEXT")[-1]
        assert action == "start"
        assert detail.startswith("launch lanes for: a-001 (sh ")
        assert detail.endswith("; after they merge, alone: a-002")

    def test_a_merged_task_with_its_branch_deleted_is_not_offered_again(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        task(repo, "a-002", depends_on="a-001")
        result = where(repo, fake_gh(tmp_path, merged=["a-001"]))
        action, detail = rows(result.stdout, "NEXT")[-1]
        assert action == "start"
        assert detail.startswith("launch lanes for: a-002 (sh ")

    def test_every_task_merged_is_complete(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        assert actions(where(repo, fake_gh(tmp_path, merged=["a-001"])).stdout)[-1] == "complete"

    def test_blocked_with_nothing_in_flight_is_reported_as_stuck(self, tmp_path: Path) -> None:
        """A dependency that nobody holds and that is not ready cannot arise, except by a cycle."""
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001", depends_on="a-002")
        task(repo, "a-002", depends_on="a-001")
        assert actions(where(repo, fake_gh(tmp_path)).stdout)[-1] == "unblock"

    def test_unreadable_pull_request_state_is_an_error_not_a_guess(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        result = where(repo, fake_gh(tmp_path, failing=True))
        assert result.returncode == ERROR
        assert "NEXT\tstart" not in result.stdout


LENSES = """\
# lens     skill             paths that bring the lens in
general    code-review
security   security-review   */auth/* *.tf
docs       -                 *.md
"""


class TestReview:
    """Each pull request in review gets one REVIEW row per lens, naming the skill to run."""

    def test_without_a_lens_file_only_the_general_review_is_suggested(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo)
        task(repo, "a-001")
        result = where(repo, fake_gh(tmp_path, in_review={"a-001": PullRequest(7, ["src/app.py"])}))
        assert result.returncode == OK
        assert rows(result.stdout, "REVIEW") == [["a-001", "#7", "general", "-", "default"]]
        assert ["review", "pull requests await review, one pass per REVIEW row: a-001"] in rows(result.stdout, "NEXT")

    def test_lenses_come_from_the_task_the_labels_and_the_paths(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo)
        write(repo, "delivery/review-lenses.conf", LENSES)
        task(repo, "a-001", review="security")
        task(repo, "a-002")
        prs = {
            "a-001": PullRequest(7, ["src/auth/login.py"], ["ai-assisted"]),
            "a-002": PullRequest(8, ["infra/main.tf"], ["review:data"]),
        }
        assert rows(where(repo, fake_gh(tmp_path, in_review=prs)).stdout, "REVIEW") == [
            ["a-001", "#7", "general", "code-review", "default"],
            ["a-001", "#7", "security", "security-review", "task,path:src/auth/login.py"],
            ["a-002", "#8", "general", "code-review", "default"],
            ["a-002", "#8", "data", "-", "label"],
            ["a-002", "#8", "security", "security-review", "path:infra/main.tf"],
        ]

    def test_a_pattern_is_matched_against_the_diff_not_expanded_in_the_checkout(self, tmp_path: Path) -> None:
        """README.md sits in the checkout; a globbed *.md would match only that and miss the diff."""
        repo = make_repo(tmp_path)
        approved_plan(repo)
        write(repo, "delivery/review-lenses.conf", LENSES)
        task(repo, "a-001")
        result = where(repo, fake_gh(tmp_path, in_review={"a-001": PullRequest(7, ["docs/guide/usage.md"])}))
        assert ["a-001", "#7", "docs", "-", "path:docs/guide/usage.md"] in rows(result.stdout, "REVIEW")

    def test_nothing_in_review_prints_no_review_rows(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        approved_plan(repo)
        write(repo, "delivery/review-lenses.conf", LENSES)
        task(repo, "a-001")
        result = where(repo, fake_gh(tmp_path))
        assert rows(result.stdout, "REVIEW") == []
        assert "review" not in actions(result.stdout)


class TestRouting:
    """The AGENTS.md block is what sends a project's requests to the orchestrator."""

    def test_a_missing_block_is_the_first_next_action(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        result = where(repo, fake_gh(tmp_path))
        assert rows(result.stdout, "ROUTING") == [["missing"]]
        assert actions(result.stdout)[0] == "install-routing"
        assert "install-routing.sh" in rows(result.stdout, "NEXT")[0][1]

    def test_install_creates_agents_md_and_where_then_sees_it(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        result = subprocess.run([SH, str(INSTALL)], cwd=repo, capture_output=True, text=True, check=False)  # noqa: S603
        assert result.stdout == "ADDED\tAGENTS.md\nADDED\tdelivery/review-lenses.conf\n"
        assert "alula" in (repo / "AGENTS.md").read_text(encoding="utf-8")
        after = where(repo, fake_gh(tmp_path))
        assert rows(after.stdout, "ROUTING") == [["present"]]
        assert "install-routing" not in actions(after.stdout)

    def test_install_appends_after_existing_content_once(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        (repo / "AGENTS.md").write_text("# Rules\n\nKeep it tidy.", encoding="utf-8")
        for _ in range(2):
            subprocess.run([SH, str(INSTALL)], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603
        text = (repo / "AGENTS.md").read_text(encoding="utf-8")
        assert text.startswith("# Rules\n\nKeep it tidy.\n\n<!-- alula:routing -->\n")
        assert text.count("<!-- alula:routing -->") == 1

    def test_install_seeds_review_lenses_that_where_reads(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        subprocess.run([SH, str(INSTALL)], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603
        approved_plan(repo)
        task(repo, "a-001")
        result = where(repo, fake_gh(tmp_path, in_review={"a-001": PullRequest(7, ["src/auth/login.py"])}))
        assert rows(result.stdout, "REVIEW") == [["a-001", "#7", "general", "-", "default"]]

    def test_install_leaves_an_edited_lens_file_alone(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path)
        write(repo, "delivery/review-lenses.conf", LENSES)
        result = subprocess.run([SH, str(INSTALL)], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603
        assert "PRESENT\tdelivery/review-lenses.conf" in result.stdout
        assert (repo / "delivery/review-lenses.conf").read_text(encoding="utf-8") == LENSES

    @pytest.mark.parametrize("script", [WHERE, INSTALL])
    def test_refuses_to_run_below_the_repository_root(self, tmp_path: Path, script: Path) -> None:
        repo = make_repo(tmp_path)
        (repo / "src").mkdir()
        env = os.environ.copy()
        env["PATH"] = f"{fake_gh(tmp_path)}{os.pathsep}{env['PATH']}"
        result = subprocess.run(  # noqa: S603
            [SH, str(script)],
            cwd=repo / "src",
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == ERROR
        assert "repository root" in result.stderr
