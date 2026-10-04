"""Behavioural tests for the follow loop.

``follow.sh`` advances a task set on its own: it reports what changed and
launches what each merge makes ready. The tests replay a scripted sequence of
task states, one per poll, and record what the loop asked the launcher to start.
"""

import subprocess
from pathlib import Path

from tests.conftest import SH

SKILLS = Path(__file__).resolve().parents[2] / ".agents" / "skills"
SCRIPT = SKILLS / "alula" / "scripts" / "follow.sh"

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


def scripted_status(tmp_path: Path, polls: list[dict[str, str]]) -> Path:
    """A status.sh that prints the next poll's states each time it runs."""
    folder = tmp_path / "polls"
    folder.mkdir()
    for n, states in enumerate(polls, start=1):
        rows = "".join(f"TASK\t{task_id}\t{state}\t-\tDo {task_id}\n" for task_id, state in states.items())
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
        repo = repo_with(tmp_path, {"a-001": "", "a-002": ""})
        status = scripted_status(
            tmp_path,
            [
                {"a-001": "in-progress", "a-002": "blocked"},
                {"a-001": "done", "a-002": "ready"},
                {"a-001": "done", "a-002": "done"},
            ],
        )
        result = follow(repo, status, recording_launcher(tmp_path))
        assert result.returncode == COMPLETE, result.stdout + result.stderr
        assert ["MERGED", "a-001"] in events(result.stdout)
        assert launched(tmp_path) == ["a-002"]
        assert events(result.stdout)[-1] == ["COMPLETE"]

    def test_already_done_work_is_not_announced_again(self, tmp_path: Path) -> None:
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(tmp_path, [{"a-001": "done"}])
        result = follow(repo, status, recording_launcher(tmp_path))
        assert events(result.stdout) == [["COMPLETE"]]

    def test_stuck_when_nothing_can_unblock_the_rest(self, tmp_path: Path) -> None:
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(tmp_path, [{"a-001": "blocked"}])
        result = follow(repo, status, recording_launcher(tmp_path))
        assert result.returncode == STUCK
        assert events(result.stdout) == [["STUCK", "a-001"]]

    def test_no_launch_only_reports(self, tmp_path: Path) -> None:
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(tmp_path, [{"a-001": "ready"}])
        follow(repo, status, recording_launcher(tmp_path), "--no-launch", "--max-polls", "2")
        assert launched(tmp_path) == []

    def test_launcher_options_pass_through(self, tmp_path: Path) -> None:
        repo = repo_with(tmp_path, {"a-001": ""})
        status = scripted_status(tmp_path, [{"a-001": "ready"}])
        follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1", "--", "--no-web")
        args = (tmp_path / "launches.log").read_text()
        assert "--no-web" in args
        assert "--max-lanes 3" in args


class TestLimits:
    def test_never_launches_what_conflicts_with_work_in_flight(self, tmp_path: Path) -> None:
        """The launcher only checks conflicts within its own batch."""
        repo = repo_with(tmp_path, {"a-001": "", "a-002": "a-001", "a-003": ""})
        status = scripted_status(tmp_path, [{"a-001": "in-progress", "a-002": "ready", "a-003": "ready"}])
        result = follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1")
        assert launched(tmp_path) == ["a-003"]
        assert ["SKIP", "a-002", "conflicts with a-001, in flight"] in events(result.stdout)

    def test_lanes_running_here_use_up_slots(self, tmp_path: Path) -> None:
        repo = repo_with(tmp_path, {"a-001": "", "a-002": ""})
        logs = repo / ".lanes" / "logs"
        logs.mkdir(parents=True)
        (logs / "a-001.log").write_text("working\n", encoding="utf-8")
        status = scripted_status(tmp_path, [{"a-001": "in-progress", "a-002": "ready"}])
        follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1", "--max-lanes", "2")
        assert "--max-lanes 1" in (tmp_path / "launches.log").read_text()

    def test_no_launch_when_every_slot_is_taken(self, tmp_path: Path) -> None:
        repo = repo_with(tmp_path, {"a-001": "", "a-002": ""})
        logs = repo / ".lanes" / "logs"
        logs.mkdir(parents=True)
        (logs / "a-001.log").write_text("working\n", encoding="utf-8")
        status = scripted_status(tmp_path, [{"a-001": "in-progress", "a-002": "ready"}])
        follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1", "--max-lanes", "1")
        assert launched(tmp_path) == []


class TestLaneOutcomes:
    def test_a_published_lane_is_announced_once(self, tmp_path: Path) -> None:
        repo = repo_with(tmp_path, {"a-001": ""})
        logs = repo / ".lanes" / "logs"
        logs.mkdir(parents=True)
        (logs / "a-001.log").write_text("done\nPUBLISHED\ta-001\thttps://example.test/pr/4\n", encoding="utf-8")
        status = scripted_status(tmp_path, [{"a-001": "in-progress"}])
        result = follow(repo, status, recording_launcher(tmp_path), "--max-polls", "3")
        assert events(result.stdout).count(["PUBLISHED", "a-001", "https://example.test/pr/4"]) == 1

    def test_a_lane_that_ended_without_a_pull_request_is_reported(self, tmp_path: Path) -> None:
        repo = repo_with(tmp_path, {"a-001": ""})
        logs = repo / ".lanes" / "logs"
        logs.mkdir(parents=True)
        (logs / "a-001.log").write_text("KEPT\ta-001\tthe worktree has changes\n", encoding="utf-8")
        status = scripted_status(tmp_path, [{"a-001": "in-progress"}])
        result = follow(repo, status, recording_launcher(tmp_path), "--max-polls", "1")
        assert events(result.stdout)[0][:2] == ["LANE-FAILED", "a-001"]

    def test_unreadable_state_is_retried_then_given_up(self, tmp_path: Path) -> None:
        repo = repo_with(tmp_path, {"a-001": ""})
        broken = tmp_path / "status.sh"
        broken.write_text("exit 1\n", encoding="utf-8")
        result = follow(repo, broken, recording_launcher(tmp_path))
        assert result.returncode == 1
        assert [e[0] for e in events(result.stdout)] == ["ERROR"] * 5
