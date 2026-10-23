"""Behavioural tests for the follow loop.

``follow.sh`` advances a task set on its own: it reports what changed and
launches what each merge makes ready. The tests replay a scripted sequence of
task states, one per poll, and record what the loop asked the launcher to start.
"""

import subprocess
from pathlib import Path

from tests.conftest import SH

SKILLS = Path(__file__).resolve().parents[2] / ".agents" / "skills"
SCRIPT = SKILLS / "delivery-orchestrator" / "scripts" / "follow.sh"

COMPLETE = 0
STUCK = 3


def repo_with(tmp_path: Path, tasks: dict[str, str]) -> Path:
    """A repository root holding task files; values are conflicts_with lists."""
    repo = tmp_path / "repo"
    (repo / "delivery" / "tasks").mkdir(parents=True)
    for task_id, conflicts in tasks.items():
        (repo / "delivery" / "tasks" / f"{task_id}.md").write_text(
            f"---\nid: {task_id}\nconflicts_with: [{conflicts}]\n---\n", encoding="utf-8"
        )
    return repo


def scripted_status(tmp_path: Path, polls: list[dict[str, str]], milestones: str = "") -> Path:
    """A status.sh that prints the next poll's states each time it runs, then any MILESTONE rows."""
    folder = tmp_path / "polls"
    folder.mkdir()
    for n, states in enumerate(polls, start=1):
        rows = "".join(f"TASK\t{task_id}\t{state}\t-\tDo {task_id}\n" for task_id, state in states.items())
        rows += milestones
        (folder / f"{n}.tsv").write_text(rows, encoding="utf-8")
    script = tmp_path / "status.sh"
    script.write_text(
        f'n=$(( $(cat "{folder}/count" 2>/dev/null || echo 0) + 1 )); echo "$n" > "{folder}/count"\n'
        f'last=$(ls "{folder}"/*.tsv | wc -l); [ "$n" -le "$last" ] || n=$last\n'
        f'cat "{folder}/$n.tsv"\n',
        encoding="utf-8",
    )
    return script


def recording_launcher(tmp_path: Path) -> Path:
    """A launch-lanes.sh that records its arguments and ids, and launches them all."""
    script = tmp_path / "launch.sh"
    record = tmp_path / "launches.log"
    script.write_text(
        f'printf "ARGS %s\\n" "$*" >> "{record}"\n'
        f'while read -r id; do printf "IDS %s\\n" "$id" >> "{record}"; '
        f'printf "LAUNCHED\\t%s\\tclaude\\tdefault\\t../lanes/%s\\n" "$id" "$id"; done\n',
        encoding="utf-8",
    )
    return script


def follow(repo: Path, status: Path, launcher: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [
            SH,
            str(SCRIPT),
            "--interval",
            "0",
            "--summary-every",
            "100000",
            "--status-script",
            str(status),
            "--launcher",
            str(launcher),
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def events(stdout: str) -> list[list[str]]:
    return [line.split("\t") for line in stdout.splitlines()]


def launched(tmp_path: Path) -> list[str]:
    record = tmp_path / "launches.log"
    if not record.exists():
        return []
    return [line.split(" ", 1)[1] for line in record.read_text().splitlines() if line.startswith("IDS ")]


class TestAdvancing:
    def test_a_merge_launches_what_it_made_ready(self, tmp_path: Path) -> None:
        """The point of the loop: nobody has to ask what is next."""
        # Given a-002 waits on a-001, which merges on the second poll
        repo = repo_with(tmp_path, {"a-001": "", "a-002": ""})
        status = scripted_status(
            tmp_path,
            [
                {"a-001": "in-progress", "a-002": "blocked"},
                {"a-001": "done", "a-002": "ready"},
                {"a-001": "done", "a-002": "done"},
            ],
        )

        # When the loop follows the set
        result = follow(repo, status, recording_launcher(tmp_path))

        # Then it reports the merge, launches a-002, and completes
        assert result.returncode == COMPLETE, result.stdout + result.stderr
        assert ["MERGED", "a-001"] in events(result.stdout)
        assert launched(tmp_path) == ["a-002"]
        assert events(result.stdout)[-1] == ["COMPLETE"]

    def test_already_done_work_is_not_announced_again(self, tmp_path: Path) -> None:
        # Given a task already done on the first poll
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(tmp_path, [{"a-001": "done"}])

        # When the loop follows the set
        result = follow(repo, status, recording_launcher(tmp_path))

        # Then it only reports completion
        assert events(result.stdout) == [["COMPLETE"]]

    def test_stuck_when_nothing_can_unblock_the_rest(self, tmp_path: Path) -> None:
        # Given a blocked task and nothing in flight
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(tmp_path, [{"a-001": "blocked"}])

        # When the loop follows the set
        result = follow(repo, status, recording_launcher(tmp_path))

        # Then it stops as stuck, naming the task
        assert result.returncode == STUCK
        assert events(result.stdout) == [["STUCK", "a-001"]]

    def test_no_launch_only_reports(self, tmp_path: Path) -> None:
        # Given a ready task
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(tmp_path, [{"a-001": "ready"}])

        # When the loop follows without launching
        follow(repo, status, recording_launcher(tmp_path), "--no-launch", "--max-polls", "2")

        # Then nothing is launched
        assert launched(tmp_path) == []

    def test_launcher_options_pass_through(self, tmp_path: Path) -> None:
        # Given a ready task
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(tmp_path, [{"a-001": "ready"}])

        # When the loop follows with a launcher option after --
        follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1", "--", "--no-web")

        # Then the launcher receives it, with the lane limit
        args = (tmp_path / "launches.log").read_text()
        assert "--no-web" in args
        assert "--max-lanes 3" in args


class TestMilestoneBoundary:
    """The loop never crosses into the next milestone; it says a person is needed."""

    def test_a_merged_milestone_stops_the_loop_for_its_review(self, tmp_path: Path) -> None:
        # Given a milestone whose last task merges, and another planned
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(
            tmp_path,
            [{"a-001": "in-progress"}, {"a-001": "done"}],
            milestones="MILESTONE\tskeleton\tmerged\ta\t-\nMILESTONE\tteam\tplanned\t-\t-\n",
        )

        # When the loop follows the set
        result = follow(repo, status, recording_launcher(tmp_path))

        # Then it stops at the merged milestone, not at completion
        assert result.returncode == COMPLETE
        assert events(result.stdout)[-1] == ["MILESTONE", "skeleton", "merged"]
        assert ["COMPLETE"] not in events(result.stdout)

    def test_an_uncut_milestone_is_reported_rather_than_started(self, tmp_path: Path) -> None:
        # Given the next milestone has no tasks yet
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(
            tmp_path,
            [{"a-001": "done"}],
            milestones="MILESTONE\tskeleton\tclosed\ta\t-\nMILESTONE\tteam\tundecomposed\t-\t-\n",
        )

        # When the loop follows the set
        result = follow(repo, status, recording_launcher(tmp_path))

        # Then it reports the milestone and launches nothing
        assert events(result.stdout) == [["MILESTONE", "team", "undecomposed"]]
        assert launched(tmp_path) == []

    def test_every_milestone_closed_is_complete(self, tmp_path: Path) -> None:
        # Given the only milestone is closed
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(tmp_path, [{"a-001": "done"}], milestones="MILESTONE\tskeleton\tclosed\ta\t-\n")

        # When the loop follows the set
        result = follow(repo, status, recording_launcher(tmp_path))

        # Then it completes
        assert events(result.stdout) == [["COMPLETE"]]


class TestLimits:
    def test_never_launches_what_conflicts_with_work_in_flight(self, tmp_path: Path) -> None:
        """The launcher only checks conflicts within its own batch."""
        # Given a-002 conflicts with a-001, which is in flight
        repo = repo_with(tmp_path, {"a-001": "", "a-002": "a-001", "a-003": ""})
        status = scripted_status(tmp_path, [{"a-001": "in-progress", "a-002": "ready", "a-003": "ready"}])

        # When the loop polls once
        result = follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1")

        # Then only a-003 launches, and a-002 is skipped with the reason
        assert launched(tmp_path) == ["a-003"]
        assert ["SKIP", "a-002", "conflicts with a-001, in flight"] in events(result.stdout)

    def test_lanes_running_here_use_up_slots(self, tmp_path: Path) -> None:
        # Given one lane already running from this checkout
        repo = repo_with(tmp_path, {"a-001": "", "a-002": ""})
        logs = repo / ".lanes" / "logs"
        logs.mkdir(parents=True)
        (logs / "a-001.log").write_text("working\n", encoding="utf-8")
        status = scripted_status(tmp_path, [{"a-001": "in-progress", "a-002": "ready"}])

        # When the loop polls once with two slots
        follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1", "--max-lanes", "2")

        # Then the launcher is offered the one slot left
        assert "--max-lanes 1" in (tmp_path / "launches.log").read_text()

    def test_no_launch_when_every_slot_is_taken(self, tmp_path: Path) -> None:
        # Given one lane already running from this checkout
        repo = repo_with(tmp_path, {"a-001": "", "a-002": ""})
        logs = repo / ".lanes" / "logs"
        logs.mkdir(parents=True)
        (logs / "a-001.log").write_text("working\n", encoding="utf-8")
        status = scripted_status(tmp_path, [{"a-001": "in-progress", "a-002": "ready"}])

        # When the loop polls once with one slot
        follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1", "--max-lanes", "1")

        # Then nothing is launched
        assert launched(tmp_path) == []


class TestLaneOutcomes:
    def test_a_published_lane_is_announced_once(self, tmp_path: Path) -> None:
        # Given a lane log that records a published pull request
        repo = repo_with(tmp_path, {"a-001": ""})
        logs = repo / ".lanes" / "logs"
        logs.mkdir(parents=True)
        (logs / "a-001.log").write_text("done\nPUBLISHED\ta-001\thttps://example.test/pr/4\n", encoding="utf-8")
        status = scripted_status(tmp_path, [{"a-001": "in-progress"}])

        # When the loop polls three times
        result = follow(repo, status, recording_launcher(tmp_path), "--max-polls", "3")

        # Then the pull request is announced once
        assert events(result.stdout).count(["PUBLISHED", "a-001", "https://example.test/pr/4"]) == 1

    def test_a_lane_that_ended_without_a_pull_request_is_reported(self, tmp_path: Path) -> None:
        # Given a lane log that ended with the lane kept
        repo = repo_with(tmp_path, {"a-001": ""})
        logs = repo / ".lanes" / "logs"
        logs.mkdir(parents=True)
        (logs / "a-001.log").write_text("KEPT\ta-001\tthe worktree has changes\n", encoding="utf-8")
        status = scripted_status(tmp_path, [{"a-001": "in-progress"}])

        # When the loop polls once
        result = follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1")

        # Then the lane is reported as failed
        assert events(result.stdout)[0][:2] == ["LANE-FAILED", "a-001"]

    def test_unreadable_state_is_retried_then_given_up(self, tmp_path: Path) -> None:
        # Given a status script that always fails
        repo = repo_with(tmp_path, {"a-001": ""})
        broken = tmp_path / "status.sh"
        broken.write_text("exit 1\n", encoding="utf-8")

        # When the loop follows
        result = follow(repo, broken, recording_launcher(tmp_path))

        # Then it reports five errors and gives up
        assert result.returncode == 1
        assert [e[0] for e in events(result.stdout)] == ["ERROR"] * 5
