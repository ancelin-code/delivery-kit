"""Behavioural tests for a use case spread over several repositories.

The planning files live in one clone; a task's ``repo`` field names the sibling
clone its change lands in. Each test builds a use case directory holding two
clones, ``home`` and ``api``, each with its own bare remote, and a fake ``gh``
that answers for whichever repository it is run in.
"""

import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.test_fourmee_decompose_scripts import validate, write_summary

SKILLS = Path(__file__).resolve().parents[2] / ".agents" / "skills"
STATUS = SKILLS / "fourmee-status" / "scripts" / "status.sh"
SNAPSHOT = SKILLS / "fourmee-status" / "scripts" / "snapshot.sh"
CLAIM = SKILLS / "fourmee-status" / "scripts" / "claim.sh"
LAUNCH = SKILLS / "fourmee" / "scripts" / "launch-lanes.sh"
PUBLISH = SKILLS / "fourmee" / "scripts" / "publish-lane.sh"
WHERE = SKILLS / "fourmee" / "scripts" / "where.sh"

# Exit codes: status.sh reports an environment error as 1, the validator a
# rejected task set as 2.
ERROR = 1
INVALID = 2

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git are required",
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def clone(tmp_path: Path, name: str) -> Path:
    """A clone at <tmp>/uc/<name> of a fresh bare remote at <tmp>/<name>.git."""
    bare = tmp_path / f"{name}.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)  # noqa: S603, S607
    git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    work = tmp_path / "uc" / name
    work.mkdir(parents=True)
    git(work, "init", "-q", "-b", "main")
    git(work, "config", "user.email", f"{name}@example.com")
    git(work, "config", "user.name", "devA")
    (work / "README.md").write_text(f"{name}\n", encoding="utf-8")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "init")
    git(work, "remote", "add", "origin", str(bare))
    git(work, "push", "-q", "-u", "origin", "main")
    git(work, "remote", "set-head", "origin", "--auto")
    return work


@pytest.fixture
def use_case(tmp_path: Path) -> tuple[Path, Path]:
    return clone(tmp_path, "home"), clone(tmp_path, "api")


def task(home: Path, task_id: str, *, repo: str | None = None, depends_on: str = "", review: str = "") -> None:
    tasks = home / "delivery" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / f"{task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\ntitle: Do {task_id}\nepic: a\ndepends_on: [{depends_on}]\n"
        f"parallel: true\nconflicts_with: []\ntier: build\n"
        f"{'' if repo is None else f'repo: {repo}\n'}"
        f"{'' if not review else f'review: [{review}]\n'}"
        "---\n\n## Acceptance criteria\n- observable\n",
        encoding="utf-8",
    )


def fake_gh(
    tmp_path: Path,
    *,
    merged: dict[str, list[str]] = {},  # noqa: B006
    in_review: dict[str, dict[str, int]] = {},  # noqa: B006
) -> Path:
    """A gh that answers for the repository it runs in, named by its directory.

    ``merged`` maps a repository to its merged task ids; ``in_review`` maps a
    repository to {task id: pull request number}. Anything else gets the
    answers a publishing lane needs: no pull request yet, then a created one.
    """
    bin_dir = tmp_path / "ghbin"
    bin_dir.mkdir(exist_ok=True)
    for repo, ids in merged.items():
        (bin_dir / f"{repo}.merged").write_text("".join(f"task/{i}\n" for i in ids), encoding="utf-8")
    for repo, prs in in_review.items():
        (bin_dir / f"{repo}.review").write_text("".join(f"task/{i}\n" for i in prs), encoding="utf-8")
        for task_id, number in prs.items():
            (bin_dir / f"{repo}.view-task_{task_id}").write_text(f"N\t{number}\n", encoding="utf-8")
    (bin_dir / "gh").write_text(
        "#!/usr/bin/env bash\n"
        f"dir={shlex.quote(str(bin_dir))}\n"
        'printf "%s\\t%s\\n" "$(basename "$PWD")" "$*" >> "$dir/calls.log"\n'
        'repo="$(basename "$(git rev-parse --show-toplevel)")"\n'
        'if [[ "$1 $2" == "pr view" ]]; then cat "$dir/$repo.view-${3//\\//_}" 2>/dev/null || exit 1; exit 0; fi\n'
        'if [[ "$1 $2" == "pr create" ]]; then\n'
        '  args=("$@")\n'
        '  for i in "${!args[@]}"; do\n'
        '    [[ "${args[$i]}" != --body-file ]] || cp "${args[$((i + 1))]}" "$dir/body.md"\n'
        "  done\n"
        '  printf "https://example.test/%s/pull/1\\n" "$repo"; exit 0\n'
        "fi\n"
        'if [[ "$*" == *"--state all"* ]]; then printf "https://example.test/%s/pull/9\\n" "$repo"; exit 0; fi\n'
        'if [[ "$*" == *"--state open"* ]]; then cat "$dir/$repo.review" 2>/dev/null; exit 0; fi\n'
        'head=""; args=("$@")\n'
        'for i in "${!args[@]}"; do [[ "${args[$i]}" != --head ]] || head="${args[$((i + 1))]}"; done\n'
        'while read -r b; do [[ -n "$head" && "$b" != "$head" ]] || printf "%s\\n" "$b"; done '
        '< <(cat "$dir/$repo.merged" 2>/dev/null)\n',
        encoding="utf-8",
    )
    (bin_dir / "gh").chmod(0o755)
    return bin_dir


def run(script: Path, args: list[str], cwd: Path, bin_dir: Path, **env: str) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", **env}
    return subprocess.run(  # noqa: S603
        ["bash", str(script), *args],  # noqa: S607
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


def states(stdout: str) -> dict[str, str]:
    return {row[1]: row[2] for row in (line.split("\t") for line in stdout.splitlines()) if row[0] == "TASK"}


def claim_in(repo: Path, task_id: str) -> None:
    result = run(CLAIM, [task_id], repo, Path("/nonexistent"))
    assert result.returncode == 0, result.stderr


class TestStatusAcrossRepositories:
    def test_a_task_is_claimed_in_the_repository_it_lands_in(self, tmp_path: Path, use_case: tuple[Path, Path]) -> None:
        home, api = use_case
        task(home, "h-001")
        task(home, "a-001", repo="api")
        claim_in(api, "a-001")

        result = run(STATUS, [], home, fake_gh(tmp_path))

        assert result.returncode == 0, result.stderr
        assert states(result.stdout) == {"a-001": "in-progress", "h-001": "ready"}

    def test_a_branch_of_the_same_name_in_another_repository_is_not_the_task(
        self, tmp_path: Path, use_case: tuple[Path, Path]
    ) -> None:
        home, api = use_case
        task(home, "h-001")
        task(home, "a-001", repo="api")
        claim_in(api, "h-001")

        result = run(STATUS, [], home, fake_gh(tmp_path, merged={"api": ["h-001"]}))

        assert states(result.stdout) == {"a-001": "ready", "h-001": "ready"}

    def test_a_merge_in_another_repository_unblocks_a_dependent_here(
        self, tmp_path: Path, use_case: tuple[Path, Path]
    ) -> None:
        """Dependencies cross repositories: the API contract lands before its consumer."""
        home, _ = use_case
        task(home, "a-001", repo="api")
        task(home, "h-001", depends_on="a-001")

        result = run(STATUS, ["--no-fetch"], home, fake_gh(tmp_path, merged={"api": ["a-001"]}))

        assert states(result.stdout) == {"a-001": "done", "h-001": "ready"}

    def test_a_snapshot_names_the_repository_and_pull_request_of_each_task(
        self, tmp_path: Path, use_case: tuple[Path, Path]
    ) -> None:
        """A connector files each task under the repository it changes, not the plan's."""
        home, _ = use_case
        task(home, "a-001", repo="api")
        task(home, "h-001", depends_on="a-001")

        result = run(SNAPSHOT, ["--no-fetch"], home, fake_gh(tmp_path, merged={"api": ["a-001"]}))

        assert result.returncode == 0, result.stderr
        tasks = {t["id"]: t for t in json.loads(result.stdout)["tasks"]}
        assert (tasks["a-001"]["repo"], tasks["a-001"]["state"]) == ("api", "done")
        assert tasks["a-001"]["pull_request"] == "https://example.test/api/pull/9"
        assert (tasks["h-001"]["repo"], tasks["h-001"]["state"]) == ("home", "ready")

    def test_a_task_in_a_repository_with_no_clone_is_an_error(
        self, tmp_path: Path, use_case: tuple[Path, Path]
    ) -> None:
        home, _ = use_case
        task(home, "w-001", repo="webapp")

        result = run(STATUS, ["--no-fetch"], home, fake_gh(tmp_path))

        assert result.returncode == ERROR
        assert "clone it beside home" in result.stderr


class TestLaunchAcrossRepositories:
    def test_a_dry_run_names_the_repository_of_each_lane(self, tmp_path: Path, use_case: tuple[Path, Path]) -> None:
        home, _ = use_case
        task(home, "h-001")
        task(home, "a-001", repo="api")

        result = run(LAUNCH, ["--dry-run", "h-001", "a-001"], home, fake_gh(tmp_path))

        lanes = [line.split("\t") for line in result.stdout.splitlines() if line.startswith("WOULD-LAUNCH")]
        assert [(lane[1], lane[6]) for lane in lanes] == [("h-001", "home"), ("a-001", "api")]

    @pytest.mark.parametrize("harness", ["claude", "copilot"])
    def test_a_lane_works_in_its_repository_and_reads_the_plan_here(
        self, tmp_path: Path, use_case: tuple[Path, Path], harness: str
    ) -> None:
        home, api = use_case
        task(home, "a-001", repo="api")
        bin_dir = fake_gh(tmp_path)
        log = tmp_path / "agent.log"
        (bin_dir / harness).write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$PWD" "$*" >> "$FAKE_LOG"\n', encoding="utf-8"
        )
        (bin_dir / harness).chmod(0o755)
        lanes = tmp_path / "uc" / "lanes"

        result = run(
            LAUNCH,
            ["--harness", harness, "--worktree-root", "../lanes", "a-001"],
            home,
            bin_dir,
            FAKE_LOG=str(log),
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert "task/a-001" in git(api, "branch", "--list", "task/a-001")
        assert "task/a-001" not in git(home, "branch", "--list", "task/a-001")
        assert git(tmp_path / "api.git", "branch", "--list", "task/a-001").strip()
        deadline = time.monotonic() + 10
        while not log.exists() or not log.read_text(encoding="utf-8").strip():
            assert time.monotonic() < deadline, "the harness was never invoked"
            time.sleep(0.1)
        recorded = log.read_text(encoding="utf-8")
        assert str(lanes.resolve() / "a-001") in recorded or str(lanes / "a-001") in recorded
        assert f"--add-dir {home}" in recorded
        assert str(home / "delivery" / "tasks" / "a-001.md") in recorded
        if harness == "copilot":
            assert "fourmee-implement/SKILL.md" in recorded

    def test_a_lane_in_this_repository_gets_no_extra_directory(
        self, tmp_path: Path, use_case: tuple[Path, Path]
    ) -> None:
        home, _ = use_case
        task(home, "h-001")
        git(home, "add", "-A")
        git(home, "commit", "-q", "-m", "plan")
        git(home, "push", "-q", "origin", "main")
        bin_dir = fake_gh(tmp_path)
        log = tmp_path / "agent.log"
        (bin_dir / "claude").write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$FAKE_LOG"\n', encoding="utf-8")
        (bin_dir / "claude").chmod(0o755)

        run(LAUNCH, ["--harness", "claude", "--worktree-root", "../lanes", "h-001"], home, bin_dir, FAKE_LOG=str(log))

        deadline = time.monotonic() + 10
        while not log.exists() or not log.read_text(encoding="utf-8").strip():
            assert time.monotonic() < deadline, "the harness was never invoked"
            time.sleep(0.1)
        recorded = log.read_text(encoding="utf-8")
        assert "--add-dir" not in recorded
        assert "/fourmee-implement delivery/tasks/h-001.md" in recorded


class TestPublishAcrossRepositories:
    def test_the_commit_and_pull_request_link_the_task_where_it_is_planned(
        self, tmp_path: Path, use_case: tuple[Path, Path]
    ) -> None:
        home, api = use_case
        task(home, "a-001", repo="api")
        git(home, "remote", "set-url", "origin", "git@example.test:org/home.git")
        git(api, "checkout", "-q", "-b", "task/a-001")
        git(api, "commit", "-q", "--allow-empty", "-m", "chore(claim): task a-001 [devA]")
        (api / "endpoint.py").write_text("x = 1\n", encoding="utf-8")
        (api / ".lane-report.md").write_text("Did it.\n", encoding="utf-8")
        bin_dir = fake_gh(tmp_path)

        result = run(PUBLISH, [str(home / "delivery" / "tasks" / "a-001.md")], api, bin_dir)

        assert result.returncode == 0, result.stderr
        link = "https://example.test/org/home/blob/HEAD/delivery/tasks/a-001.md"
        assert f"Task: {link}" in git(api, "log", "-1", "--format=%b")
        assert f"Task: [delivery/tasks/a-001.md]({link})" in (bin_dir / "body.md").read_text(encoding="utf-8")


class TestValidateAcrossRepositories:
    def test_a_repo_with_a_clone_beside_this_one_is_valid(self, use_case: tuple[Path, Path]) -> None:
        home, _ = use_case
        task(home, "a-001", repo="api")
        write_summary(home / "delivery" / "tasks")
        assert validate(home / "delivery" / "tasks").returncode == 0

    def test_a_repo_with_no_clone_is_rejected(self, use_case: tuple[Path, Path]) -> None:
        home, _ = use_case
        task(home, "w-001", repo="webapp")
        write_summary(home / "delivery" / "tasks")
        result = validate(home / "delivery" / "tasks")
        assert result.returncode == INVALID
        assert "clone it beside home" in result.stdout + result.stderr

    @pytest.mark.parametrize("bad", ["../api", "org/api", ".."])
    def test_a_repo_must_be_a_plain_directory_name(self, use_case: tuple[Path, Path], bad: str) -> None:
        home, _ = use_case
        task(home, "a-001", repo=bad)
        write_summary(home / "delivery" / "tasks")
        result = validate(home / "delivery" / "tasks")
        assert result.returncode == INVALID
        assert "directory name of a sibling clone" in result.stdout + result.stderr


class TestReviewAcrossRepositories:
    def test_a_pull_request_is_read_from_its_repository_and_named_with_it(
        self, tmp_path: Path, use_case: tuple[Path, Path]
    ) -> None:
        home, _ = use_case
        (home / "delivery").mkdir(exist_ok=True)
        (home / "delivery" / "prd.md").write_text("# PRD\n\n**Status:** approved\n", encoding="utf-8")
        (home / "delivery" / "decomposition.md").write_text(
            "# Plan\n\n**Status:** approved\n\n**Run as:** lanes\n", encoding="utf-8"
        )
        task(home, "a-001", repo="api")
        task(home, "h-001")
        bin_dir = fake_gh(tmp_path, in_review={"api": {"a-001": 7}, "home": {"h-001": 3}})

        result = run(WHERE, ["--no-fetch"], home, bin_dir)

        assert result.returncode == 0, result.stderr
        reviews = [line.split("\t")[1:3] for line in result.stdout.splitlines() if line.startswith("REVIEW\t")]
        assert reviews == [["a-001", "api#7"], ["h-001", "#3"]]
