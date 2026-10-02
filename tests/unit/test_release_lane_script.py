"""Behavioural tests for the lane release.

``release-lane.sh`` deletes a claim on the shared remote, so the tests are mostly
about the claims it must leave alone: a lane with work in it, and a branch that
is no longer this lane's claim.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.test_publish_lane_script import claimed_lane, git

SKILLS = Path(__file__).resolve().parents[2] / ".agents" / "skills"
SCRIPT = SKILLS / "fourmee" / "scripts" / "release-lane.sh"

RELEASED = 0
USAGE_ERROR = 1
KEPT = 3

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git are required",
)


def release(lane: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "delivery/tasks/a-001.md"],  # noqa: S607
        cwd=lane,
        capture_output=True,
        text=True,
        check=False,
    )


def remote_has_claim(tmp_path: Path) -> bool:
    refs = git(tmp_path / "origin.git", "for-each-ref", "--format=%(refname)", "refs/heads/task/").stdout
    return "refs/heads/task/a-001" in refs


class TestRelease:
    def test_an_untouched_lane_gives_its_task_back(self, tmp_path: Path) -> None:
        """A session that died at startup must not hold the task until someone notices."""
        lane = claimed_lane(tmp_path)

        result = release(lane)

        assert result.returncode == RELEASED, result.stderr
        assert result.stdout == "RELEASED\ta-001\n"
        assert not remote_has_claim(tmp_path)

    def test_removes_the_worktree_and_local_branch(self, tmp_path: Path) -> None:
        """Otherwise the next launch finds the path taken and skips the task."""
        lane = claimed_lane(tmp_path)

        release(lane)

        assert not lane.exists()
        assert "task/a-001" not in git(tmp_path / "dev", "branch", "--list").stdout

    def test_keeps_a_lane_with_uncommitted_work(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('half done')\n", encoding="utf-8")

        result = release(lane)

        assert result.returncode == KEPT
        assert "has changes" in result.stdout
        assert remote_has_claim(tmp_path)
        assert (lane / "widget.py").exists()

    def test_keeps_a_lane_that_committed(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")
        git(lane, "add", "widget.py")
        git(lane, "commit", "-q", "-m", "feat(a): add the widget")

        result = release(lane)

        assert result.returncode == KEPT
        assert "commits past the claim" in result.stdout
        assert remote_has_claim(tmp_path)

    def test_never_deletes_a_branch_that_moved_on(self, tmp_path: Path) -> None:
        """The remote is the truth: someone may have pushed to the task since."""
        lane = claimed_lane(tmp_path)
        other = tmp_path / "other"
        subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)  # noqa: S603, S607
        git(other, "config", "user.email", "o@example.com")
        git(other, "config", "user.name", "other")
        git(other, "checkout", "-q", "task/a-001")
        git(other, "commit", "-q", "--allow-empty", "-m", "feat(a): someone else's work")
        git(other, "push", "-q", "origin", "task/a-001")

        result = release(lane)

        assert result.returncode == KEPT
        assert "no longer this claim" in result.stdout
        assert remote_has_claim(tmp_path)

    def test_refuses_to_run_off_the_task_branch(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        git(lane, "checkout", "-q", "-b", "elsewhere")

        result = release(lane)

        assert result.returncode == USAGE_ERROR
        assert remote_has_claim(tmp_path)
