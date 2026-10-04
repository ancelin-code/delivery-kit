"""Behavioural tests for the lane publisher.

``publish-lane.sh`` is the step between an unattended lane and the pull request
a human reviews, so the tests drive it the way the launcher does: in a claimed
lane worktree, against a shared bare remote, with ``gh`` stubbed to record what
it was asked to open.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.conftest import SH

SKILLS = Path(__file__).resolve().parents[2] / ".agents" / "skills"
SCRIPT = SKILLS / "alula" / "scripts" / "publish-lane.sh"
CLAIM = SKILLS / "alula-status" / "scripts" / "claim.sh"

OK = 0
USAGE_ERROR = 1
NOTHING = 3
URL = "https://example.test/pr/7"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git is required",
)

FAKE_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr view")
    [[ -n "${GH_EXISTING:-}" ]] || exit 1
    printf '%s %s\\n' "${GH_EXISTING_STATE:-OPEN}" "$GH_EXISTING" ;;
  "pr create")
    if [[ -n "${GH_NO_LABEL:-}" && " $* " == *" --label "* ]]; then exit 1; fi
    while (($# > 0)); do
      [[ "$1" == --body-file ]] && cp "$2" "$GH_BODY"
      shift
    done
    printf 'Creating draft pull request\\n%s\\n' "$GH_URL" ;;
esac
"""


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)  # noqa: S603, S607


def claimed_lane(tmp_path: Path, *, title: str = "Do a-001", task_type: str | None = None) -> Path:
    """A lane worktree on task/a-001 whose claim is already on the shared remote."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)  # noqa: S603, S607
    dev = tmp_path / "dev"
    dev.mkdir()
    git(dev, "init", "-q", "-b", "main")
    git(dev, "config", "user.email", "dev@example.com")
    git(dev, "config", "user.name", "dev")
    tasks = dev / "delivery" / "tasks"
    tasks.mkdir(parents=True)
    type_line = "" if task_type is None else f"type: {task_type}\n"
    (tasks / "a-001.md").write_text(
        f"---\nid: a-001\ntitle: {title}\n{type_line}epic: a\ndepends_on: []\ntier: build\n---\n\n"
        "## Context\n\nWhy.\n\n## Acceptance criteria\n\n- the widget renders\n\n## Validation\n\nRun it.\n",
        encoding="utf-8",
    )
    git(dev, "add", "-A")
    git(dev, "commit", "-q", "-m", "init")
    git(dev, "remote", "add", "origin", str(bare))
    git(dev, "push", "-q", "origin", "HEAD:refs/heads/main")
    lane = tmp_path / "lanes" / "a-001"
    git(dev, "worktree", "add", "-q", "-b", "task/a-001", str(lane))
    subprocess.run([SH, str(CLAIM), "a-001"], cwd=lane, capture_output=True, check=True)  # noqa: S603
    return lane


def publish(lane: Path, tmp_path: Path, **env_extra: str) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8")
    gh.chmod(0o755)
    env = os.environ.copy()
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env['PATH']}",
        GH_LOG=str(tmp_path / "gh.log"),
        GH_BODY=str(tmp_path / "body.md"),
        GH_URL=URL,
        **env_extra,
    )
    (tmp_path / "gh.log").touch()
    return subprocess.run(  # noqa: S603
        [SH, str(SCRIPT), "delivery/tasks/a-001.md"],
        cwd=lane,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def remote_subject(tmp_path: Path) -> str:
    return git(tmp_path / "origin.git", "log", "-1", "--format=%s", "task/a-001").stdout.strip()


class TestPublishing:
    def test_a_finished_lane_becomes_a_draft_pull_request(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")

        result = publish(lane, tmp_path)

        assert result.returncode == OK, result.stderr
        assert result.stdout == f"PUBLISHED\ta-001\t{URL}\n"
        assert remote_subject(tmp_path) == "feat(a): do a-001"
        create = next(line for line in (tmp_path / "gh.log").read_text().splitlines() if line.startswith("pr create"))
        assert "--draft" in create
        assert "--label ai-assisted" in create

    def test_the_body_carries_the_criteria_and_the_report(self, tmp_path: Path) -> None:
        """The reviewer checks the diff against the criteria, and the report says what was run."""
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")
        (lane / ".lane-report.md").write_text("Validation run: pytest, 3 passed.\n", encoding="utf-8")

        publish(lane, tmp_path)

        body = (tmp_path / "body.md").read_text(encoding="utf-8")
        assert "- the widget renders" in body
        assert "Validation run: pytest, 3 passed." in body
        assert "Run it." not in body, "the section after the criteria leaked into the body"

    def test_the_report_is_never_committed(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")
        (lane / ".lane-report.md").write_text("report\n", encoding="utf-8")

        publish(lane, tmp_path)

        files = git(tmp_path / "origin.git", "ls-tree", "-r", "--name-only", "task/a-001").stdout.split()
        assert "widget.py" in files
        assert ".lane-report.md" not in files

    @pytest.mark.parametrize(
        "template",
        [
            ".github/pull_request_template.md",
            "docs/PULL_REQUEST_TEMPLATE.md",
            ".github/PULL_REQUEST_TEMPLATE/feature.md",
        ],
    )
    def test_a_repository_template_makes_the_report_the_whole_body(self, tmp_path: Path, template: str) -> None:
        """The lane fills the template; wrapping it in the kit's own sections would break it."""
        lane = claimed_lane(tmp_path)
        (lane / template).parent.mkdir(parents=True, exist_ok=True)
        (lane / template).write_text("## Summary\n\n## Testing\n", encoding="utf-8")
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")
        filled = "## Summary\n\nAdds the widget. Task: delivery/tasks/a-001.md\n\n## Testing\n\npytest\n"
        (lane / ".lane-report.md").write_text(filled, encoding="utf-8")

        publish(lane, tmp_path)

        assert (tmp_path / "body.md").read_text(encoding="utf-8") == filled

    def test_without_a_report_the_template_does_not_hide_the_criteria(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        (lane / ".github").mkdir()
        (lane / ".github" / "pull_request_template.md").write_text("## Summary\n", encoding="utf-8")
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")

        publish(lane, tmp_path)

        body = (tmp_path / "body.md").read_text(encoding="utf-8")
        assert "- the widget renders" in body
        assert "wrote no report" in body

    def test_says_when_the_lane_wrote_no_report(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")

        publish(lane, tmp_path)

        assert "wrote no report" in (tmp_path / "body.md").read_text(encoding="utf-8")

    def test_a_lane_that_left_no_change_publishes_nothing(self, tmp_path: Path) -> None:
        """A lane that stopped on a bad task reverts its attempt; no pull request may open."""
        lane = claimed_lane(tmp_path)
        (lane / ".lane-report.md").write_text("Stopped: the task is wrong.\n", encoding="utf-8")

        result = publish(lane, tmp_path)

        assert result.returncode == NOTHING
        assert result.stdout.startswith("NOTHING\ta-001")
        assert not (tmp_path / "gh.log").read_text(), "gh must not be called"

    def test_publishes_commits_the_lane_made_itself(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")
        git(lane, "add", "widget.py")
        git(lane, "commit", "-q", "-m", "feat(a): add the widget")

        result = publish(lane, tmp_path)

        assert result.returncode == OK, result.stderr
        assert remote_subject(tmp_path) == "feat(a): add the widget"


class TestCommitSubject:
    def test_uses_the_task_type(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path, title="Stop the loader dropping footnotes", task_type="fix")
        (lane / "loader.py").write_text("x = 1\n", encoding="utf-8")

        publish(lane, tmp_path)

        assert remote_subject(tmp_path) == "fix(a): stop the loader dropping footnotes"

    def test_leaves_a_leading_acronym_alone(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path, title="DITA conrefs resolve")
        (lane / "loader.py").write_text("x = 1\n", encoding="utf-8")

        publish(lane, tmp_path)

        assert remote_subject(tmp_path) == "feat(a): DITA conrefs resolve"


class TestPullRequest:
    def test_a_rerun_pushes_without_opening_a_second_pull_request(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")

        result = publish(lane, tmp_path, GH_EXISTING=URL)

        assert result.stdout == f"PUBLISHED\ta-001\t{URL}\n"
        assert "pr create" not in (tmp_path / "gh.log").read_text()

    def test_a_rerun_opens_a_pull_request_that_is_missing(self, tmp_path: Path) -> None:
        """Re-running is the recovery path, so an already pushed lane must still publish."""
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")
        git(lane, "add", "widget.py")
        git(lane, "commit", "-q", "-m", "feat(a): add the widget")
        git(lane, "push", "-q", "origin", "HEAD:refs/heads/task/a-001")

        result = publish(lane, tmp_path)

        assert result.stdout == f"PUBLISHED\ta-001\t{URL}\n"
        assert "pr create" in (tmp_path / "gh.log").read_text()

    def test_a_closed_pull_request_is_not_reused(self, tmp_path: Path) -> None:
        """A relaunched task needs a new pull request, not the one that was closed."""
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")

        result = publish(lane, tmp_path, GH_EXISTING="https://example.test/pr/2", GH_EXISTING_STATE="CLOSED")

        assert result.stdout == f"PUBLISHED\ta-001\t{URL}\n"
        assert "pr create" in (tmp_path / "gh.log").read_text()

    def test_opens_the_pull_request_without_a_missing_label(self, tmp_path: Path) -> None:
        """The pull request is the point; a repository without the label must not block it."""
        lane = claimed_lane(tmp_path)
        (lane / "widget.py").write_text("print('widget')\n", encoding="utf-8")

        result = publish(lane, tmp_path, GH_NO_LABEL="1")

        assert result.returncode == OK, result.stderr
        assert result.stdout == f"PUBLISHED\ta-001\t{URL}\n"
        assert "ai-assisted label could not be applied" in result.stderr

    def test_refuses_to_run_off_the_task_branch(self, tmp_path: Path) -> None:
        lane = claimed_lane(tmp_path)
        git(lane, "checkout", "-q", "-b", "elsewhere")

        result = publish(lane, tmp_path)

        assert result.returncode == USAGE_ERROR
        assert "not on task/a-001" in result.stderr
