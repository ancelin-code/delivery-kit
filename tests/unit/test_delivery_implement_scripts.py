"""Behavioural tests for the delivery-implement skill's bash helper script.

``detect-repo-contract.sh`` is driven end to end against a real throwaway git repository.
"""

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from tests.conftest import SH

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / ".agents" / "skills" / "delivery-implement" / "scripts"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None or shutil.which("git") is None,
    reason="jq and git are required to exercise the delivery-implement helper scripts",
)


def run_script(
    script: str,
    args: Sequence[str],
    *,
    bin_dir: Path | None = None,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        env.setdefault("HOME", str(bin_dir.parent))
    if extra_env:
        env.update(extra_env)
    # S603/S607: a test harness deliberately invoking a repo script via `bash` with a stub
    # `jira` ahead of it on PATH where needed; every input is test-local.
    return subprocess.run(  # noqa: S603
        [SH, str(SCRIPTS_DIR / script), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
    )


def rows_of(stdout: str) -> list[list[str]]:
    """Split the scripts' TSV stdout into a list of tab-separated fields per line."""
    return [line.split("\t") for line in stdout.splitlines() if line.strip()]


def first(rows: list[list[str]], key: str) -> str | None:
    """Value of the first row whose first field is ``key``; ``None`` if absent."""
    return next((row[1] if len(row) > 1 else "" for row in rows if row[0] == key), None)


def every(rows: list[list[str]], key: str) -> list[list[str]]:
    """Trailing fields of every row whose first field is ``key`` (repeatable rows)."""
    return [row[1:] for row in rows if row[0] == key]


def git(repo_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a `git` subcommand inside `repo_dir`; test-local input only."""
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )


def init_repo(repo_dir: Path) -> None:
    """Initialise a git repository with one commit on its default branch."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    git(repo_dir, "init", "-q", "-b", "master")
    git(repo_dir, "config", "user.email", "test@example.com")
    git(repo_dir, "config", "user.name", "Test")
    (repo_dir / "README.md").write_text("hello\n", encoding="utf-8")
    git(repo_dir, "add", "README.md")
    git(repo_dir, "commit", "-q", "-m", "initial commit")


class TestDetectRepoContract:
    """detect-repo-contract.sh - instructions, task runner, CODEOWNERS, and history samples."""

    def test_dies_outside_a_git_repository(self, tmp_path: Path) -> None:
        # Given a plain directory with no git repository
        plain_dir = tmp_path / "plain"
        plain_dir.mkdir()

        # When the script runs there
        result = run_script("detect-repo-contract.sh", [], cwd=plain_dir)

        # Then it dies rather than guessing repository facts
        assert result.returncode != 0
        assert "not inside a git repository" in result.stderr

    def test_reports_none_with_no_instructions_or_runner(self, tmp_path: Path) -> None:
        # Given a bare repository with nothing to detect
        repo = tmp_path / "repo"
        init_repo(repo)

        # When the script runs
        result = run_script("detect-repo-contract.sh", [], cwd=repo)

        # Then instructions, runner, and CODEOWNERS are all reported absent
        rows = rows_of(result.stdout)
        assert first(rows, "INSTRUCTIONS") == "none"
        assert first(rows, "RUNNER") == "none"
        assert first(rows, "CODEOWNERS") == "none"

    def test_prefers_agents_md_over_claude_md(self, tmp_path: Path) -> None:
        # Given both instruction files exist
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
        (repo / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")

        # When the script runs
        result = run_script("detect-repo-contract.sh", [], cwd=repo)

        # Then AGENTS.md wins, per the documented candidate order
        assert first(rows_of(result.stdout), "INSTRUCTIONS") == "AGENTS.md"

    def test_make_runner_lists_its_targets(self, tmp_path: Path) -> None:
        # Given a Makefile with two real targets
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / "Makefile").write_text("lint:\n\techo lint\ntest:\n\techo test\n", encoding="utf-8")

        # When the script runs
        result = run_script("detect-repo-contract.sh", [], cwd=repo)

        # Then the runner is make, and both targets come back as TASK rows
        rows = rows_of(result.stdout)
        assert first(rows, "RUNNER") == "make"
        assert sorted(row[0] for row in every(rows, "TASK")) == ["lint", "test"]

    def test_codeowners_fallback_locations(self, tmp_path: Path) -> None:
        # Given only the .github CODEOWNERS location is used
        repo = tmp_path / "repo"
        init_repo(repo)
        (repo / ".github").mkdir()
        (repo / ".github" / "CODEOWNERS").write_text("* @team\n", encoding="utf-8")

        # When the script runs
        result = run_script("detect-repo-contract.sh", [], cwd=repo)

        # Then that path is reported instead of the root-level default
        assert first(rows_of(result.stdout), "CODEOWNERS") == ".github/CODEOWNERS"

    def test_branch_samples_exclude_default_branch_names(self, tmp_path: Path) -> None:
        # Given a feature branch alongside the default branch
        repo = tmp_path / "repo"
        init_repo(repo)
        git(repo, "branch", "feature/thing")

        # When the script runs
        result = run_script("detect-repo-contract.sh", [], cwd=repo)

        # Then the default branch is excluded from the samples and the feature branch is kept
        samples = [row[0] for row in every(rows_of(result.stdout), "BRANCH_SAMPLE")]
        assert "master" not in samples
        assert "feature/thing" in samples


def test_every_helper_script_is_present() -> None:
    """Guard against a script being renamed or removed without updating this suite."""
    expected = {"detect-repo-contract.sh"}
    assert expected == {path.name for path in SCRIPTS_DIR.iterdir()}
