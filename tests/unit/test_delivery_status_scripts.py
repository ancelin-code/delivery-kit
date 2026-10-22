"""Behavioural tests for the delivery-status skill's bash helper scripts.

``claim.sh`` is driven against real throwaway git repositories: a bare repository
stands in for the shared remote and one clone per simulated developer. The claim
protocol is a concurrency mechanism, so the tests assert its behaviour under a
simultaneous race as well as in the ordinary sequential case.
"""

import json
import os
import shlex
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.conftest import SH

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / ".agents" / "skills" / "delivery-status" / "scripts"

# Exit codes of claim.sh; callers branch on these rather than on its output text.
CLAIM_WON = 0
CLAIM_ERROR = 1
CLAIM_HELD = 2

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="bash and git are required to exercise the delivery-status helper scripts",
)


def git(repo_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a `git` subcommand inside `repo_dir`; test-local input only."""
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=True,
    )


def run_claim(
    args: list[str],
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    # S603/S607: a test harness deliberately invoking a repo script via `bash`;
    # every input is test-local.
    return subprocess.run(  # noqa: S603
        [SH, str(SCRIPTS_DIR / "claim.sh"), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
    )


def rows_of(stdout: str) -> list[list[str]]:
    """Split the script's TSV stdout into a list of tab-separated fields per line."""
    return [line.split("\t") for line in stdout.splitlines() if line.strip()]


def first(rows: list[list[str]], key: str) -> str | None:
    """Value of the first row whose first field is ``key``; ``None`` if absent."""
    return next((row[1] if len(row) > 1 else "" for row in rows if row[0] == key), None)


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A bare repository seeded with one commit on ``main``, standing in for the remote."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)  # noqa: S603, S607
    git(bare, "symbolic-ref", "HEAD", "refs/heads/main")

    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    git(seed, "config", "user.email", "seed@example.com")
    git(seed, "config", "user.name", "Seed")
    (seed / "README.md").write_text("hello\n", encoding="utf-8")
    git(seed, "add", "README.md")
    git(seed, "commit", "-q", "-m", "initial commit")
    git(seed, "push", "-q", str(bare), "HEAD:refs/heads/main")
    return bare


def developer(tmp_path: Path, origin_path: Path, name: str) -> Path:
    """Clone `origin_path` as a developer working copy identified by `name`."""
    clone = tmp_path / name
    subprocess.run(  # noqa: S603
        ["git", "clone", "-q", str(origin_path), str(clone)],  # noqa: S607
        check=True,
    )
    git(clone, "config", "user.email", f"{name}@example.com")
    git(clone, "config", "user.name", name)
    return clone


class TestClaimValidation:
    """claim.sh - argument and environment checks before anything is pushed."""

    def test_requires_a_task_id(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        result = run_claim([], cwd=dev)
        assert result.returncode == CLAIM_ERROR

    @pytest.mark.parametrize("bad_id", ["Ingestion-003", "ingestion/003", "../escape", "ingestion 003"])
    def test_rejects_ids_that_are_not_slugs(self, tmp_path: Path, origin: Path, bad_id: str) -> None:
        dev = developer(tmp_path, origin, "devA")
        result = run_claim([bad_id], cwd=dev)
        assert result.returncode == CLAIM_ERROR
        assert "invalid task id" in result.stderr

    def test_rejects_an_id_that_looks_like_an_option(self, tmp_path: Path, origin: Path) -> None:
        """A leading dash is refused as an unknown flag rather than silently claimed."""
        dev = developer(tmp_path, origin, "devA")
        result = run_claim(["-leading"], cwd=dev)
        assert result.returncode == CLAIM_ERROR
        assert "unknown option" in result.stderr

    def test_a_dashed_id_can_still_be_passed_after_a_separator(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        result = run_claim(["--", "-leading"], cwd=dev)
        assert result.returncode == CLAIM_ERROR
        assert "invalid task id" in result.stderr

    def test_dies_outside_a_git_repository(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        result = run_claim(["ingestion-003"], cwd=plain)
        assert result.returncode == CLAIM_ERROR
        assert "not inside a git repository" in result.stderr

    def test_dies_when_the_remote_is_unknown(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        result = run_claim(["--remote", "upstream", "ingestion-003"], cwd=dev)
        assert result.returncode == CLAIM_ERROR
        assert "is not configured" in result.stderr

    def test_dies_when_the_claimant_is_anonymous(self, tmp_path: Path, origin: Path) -> None:
        """A claim that cannot name its owner is worthless as a coordination record."""
        dev = developer(tmp_path, origin, "devA")
        git(dev, "config", "--unset", "user.name")
        result = run_claim(
            ["ingestion-003"],
            cwd=dev,
            extra_env={"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull},
        )
        assert result.returncode == CLAIM_ERROR
        assert "user.name" in result.stderr


class TestClaimProtocol:
    """claim.sh - the create-only branch push used as a distributed lock."""

    def test_claims_a_free_task(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        result = run_claim(["ingestion-003"], cwd=dev)
        assert result.returncode == CLAIM_WON
        rows = rows_of(result.stdout)
        assert first(rows, "CLAIMED") == "ingestion-003"
        assert first(rows, "BRANCH") == "task/ingestion-003"
        assert first(rows, "CLAIMANT") == "devA"
        remote_branches = git(origin, "for-each-ref", "--format=%(refname)", "refs/heads/").stdout
        assert "refs/heads/task/ingestion-003" in remote_branches

    def test_rejects_a_claim_on_a_held_task(self, tmp_path: Path, origin: Path) -> None:
        """The regression guard: both developers sit on the same base commit.

        A plain push of HEAD would be a no-op here and exit 0, handing the task to a
        second developer. The claim commit makes the push distinct, so it is rejected.
        """
        holder = developer(tmp_path, origin, "devA")
        latecomer = developer(tmp_path, origin, "devB")
        assert git(holder, "rev-parse", "HEAD").stdout == git(latecomer, "rev-parse", "HEAD").stdout

        assert run_claim(["ingestion-003"], cwd=holder).returncode == CLAIM_WON
        result = run_claim(["ingestion-003"], cwd=latecomer)

        assert result.returncode == CLAIM_HELD
        rows = rows_of(result.stdout)
        assert first(rows, "HELD") == "ingestion-003"

    def test_names_the_holder_of_a_claimed_task(self, tmp_path: Path, origin: Path) -> None:
        holder = developer(tmp_path, origin, "devA")
        latecomer = developer(tmp_path, origin, "devB")
        run_claim(["ingestion-003"], cwd=holder)

        result = run_claim(["ingestion-003"], cwd=latecomer)

        assert first(rows_of(result.stdout), "HOLDER") is not None
        assert "devA" in result.stdout

    def test_a_simultaneous_race_has_exactly_one_winner(self, tmp_path: Path, origin: Path) -> None:
        devs = [developer(tmp_path, origin, f"dev{n}") for n in ("A", "B", "C")]

        def claim(dev: Path) -> int:
            return run_claim(["ingestion-003"], cwd=dev).returncode

        with ThreadPoolExecutor(max_workers=len(devs)) as pool:
            codes = list(pool.map(claim, devs))

        assert codes.count(CLAIM_WON) == 1, f"expected exactly one winner, got {codes}"
        assert all(code in (CLAIM_WON, CLAIM_HELD) for code in codes), f"unexpected failure among {codes}"

    def test_independent_tasks_do_not_contend(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        assert run_claim(["ingestion-003"], cwd=dev).returncode == CLAIM_WON
        assert run_claim(["api-001"], cwd=dev).returncode == CLAIM_WON

    def test_a_lost_claim_leaves_no_local_trace(self, tmp_path: Path, origin: Path) -> None:
        """Building the claim commit with commit-tree means a lost race needs no cleanup."""
        holder = developer(tmp_path, origin, "devA")
        latecomer = developer(tmp_path, origin, "devB")
        run_claim(["ingestion-003"], cwd=holder)
        before = git(latecomer, "rev-parse", "HEAD").stdout

        run_claim(["ingestion-003"], cwd=latecomer)

        assert git(latecomer, "rev-parse", "HEAD").stdout == before
        assert git(latecomer, "status", "--porcelain").stdout == ""


class TestClaimBranchAdvance:
    """claim.sh - what happens to the local branch once a claim is won."""

    def _on_task_branch(self, tmp_path: Path, origin: Path, task_id: str) -> Path:
        dev = developer(tmp_path, origin, "devA")
        git(dev, "checkout", "-q", "-b", f"task/{task_id}")
        return dev

    def test_advances_the_local_task_branch_to_the_claim_commit(self, tmp_path: Path, origin: Path) -> None:
        dev = self._on_task_branch(tmp_path, origin, "ingestion-003")
        result = run_claim(["ingestion-003"], cwd=dev)

        rows = rows_of(result.stdout)
        assert first(rows, "ADVANCED") == "task/ingestion-003"
        assert git(dev, "rev-parse", "HEAD").stdout.strip() == first(rows, "COMMIT")

    def test_a_plain_push_goes_to_the_claimed_branch(self, tmp_path: Path, origin: Path) -> None:
        """A branch started from the remote default branch tracks it until the claim says otherwise."""
        dev = developer(tmp_path, origin, "devA")
        git(dev, "checkout", "-q", "-b", "task/ingestion-003", "--track", "origin/main")

        result = run_claim(["ingestion-003"], cwd=dev)

        assert first(rows_of(result.stdout), "UPSTREAM") == "origin/task/ingestion-003"
        (dev / "work.txt").write_text("done\n", encoding="utf-8")
        git(dev, "add", "work.txt")
        git(dev, "commit", "-q", "-m", "feat: work")
        git(dev, "push", "-q")
        assert (
            git(dev, "ls-remote", "origin", "refs/heads/task/ingestion-003").stdout.split()[0]
            == git(dev, "rev-parse", "HEAD").stdout.strip()
        )
        assert (
            git(dev, "ls-remote", "origin", "refs/heads/main").stdout.split()[0]
            != git(dev, "rev-parse", "HEAD").stdout.strip()
        )

    def test_no_advance_leaves_the_local_branch_alone(self, tmp_path: Path, origin: Path) -> None:
        dev = self._on_task_branch(tmp_path, origin, "ingestion-003")
        before = git(dev, "rev-parse", "HEAD").stdout

        result = run_claim(["--no-advance", "ingestion-003"], cwd=dev)

        assert result.returncode == CLAIM_WON
        assert git(dev, "rev-parse", "HEAD").stdout == before

    def test_a_dirty_worktree_is_never_reset(self, tmp_path: Path, origin: Path) -> None:
        """Advancing is a convenience; it must never discard uncommitted work."""
        dev = self._on_task_branch(tmp_path, origin, "ingestion-003")
        (dev / "scratch.txt").write_text("work in progress\n", encoding="utf-8")
        git(dev, "add", "scratch.txt")

        result = run_claim(["ingestion-003"], cwd=dev)

        assert result.returncode == CLAIM_WON
        assert first(rows_of(result.stdout), "ADVANCED") is None
        assert (dev / "scratch.txt").read_text(encoding="utf-8") == "work in progress\n"


def run_status(
    args: list[str], *, cwd: Path, bin_dir: Path | None = None, path: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run status.sh against a fake gh with no pull requests unless told otherwise.

    status.sh requires gh, and the real one cannot answer for a throwaway repo.
    """
    env = os.environ.copy()
    if path is not None:
        env["PATH"] = path
    else:
        env["PATH"] = f"{bin_dir or fake_gh(cwd.parent)}{os.pathsep}{env['PATH']}"
    return subprocess.run(  # noqa: S603
        [SH, str(SCRIPTS_DIR / "status.sh"), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
    )


def fake_gh(
    tmp_path: Path,
    *,
    merged: list[str] = [],  # noqa: B006
    merged_long_ago: list[str] = [],  # noqa: B006
    open_prs: list[tuple[str, bool]] = [],  # noqa: B006
    urls: dict[str, str] = {},  # noqa: B006
) -> Path:
    """A stand-in for gh that answers the pull request queries status.sh makes.

    merged_long_ago holds tasks past the bulk query's window: gh only returns
    them to a query naming their branch with --head.

    open_prs carries (task-id, is_draft), because draft is the whole distinction
    between a lane still working and a task handed to a reviewer.

    urls maps a task id to the pull request snapshot.sh asks for by branch.
    """
    bin_dir = tmp_path / "ghbin"
    bin_dir.mkdir(exist_ok=True)
    merged_out = "".join(f"task/{task_id}\n" for task_id in merged)
    every_merged = " ".join(f"task/{task_id}" for task_id in [*merged, *merged_long_ago])
    open_out = "".join(f"task/{task_id}\n" for task_id, draft in open_prs if not draft)
    url_cases = "".join(f"    task/{task_id}) printf '%s\\n' {shlex.quote(url)} ;;\n" for task_id, url in urls.items())
    stub = bin_dir / "gh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'head=""\n'
        'args=("$@")\n'
        'for i in "${!args[@]}"; do [[ "${args[$i]}" != --head ]] || head="${args[$((i + 1))]}"; done\n'
        'if [[ "$*" == *"--state all"* ]]; then\n'
        '  case "$head" in\n'
        f"{url_cases}"
        "    *) printf '\\n' ;;\n"
        "  esac\n"
        'elif [[ "$*" == *"--state merged"* && -n "$head" ]]; then\n'
        f'  for b in {every_merged}; do [[ "$b" != "$head" ]] || printf \'%s\\n\' "$b"; done\n'
        'elif [[ "$*" == *"--state merged"* ]]; then\n'
        f"  printf '%s' {shlex.quote(merged_out)}\n"
        'elif [[ "$*" == *"--state open"* ]]; then\n'
        f"  printf '%s' {shlex.quote(open_out)}\n"
        "fi\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return bin_dir


def write_task(repo: Path, task_id: str, *, depends_on: str = "") -> None:
    tasks = repo / "delivery" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / f"{task_id}.md").write_text(
        "---\n"
        f"id: {task_id}\n"
        f"title: Do {task_id}\n"
        "epic: ingestion\n"
        f"depends_on: [{depends_on}]\n"
        "parallel: true\n"
        "conflicts_with: []\n"
        "tier: build\n"
        "---\n\n## Acceptance criteria\n- observable\n",
        encoding="utf-8",
    )


def task_rows(stdout: str) -> dict[str, list[str]]:
    """Map task id to its TASK row fields (id, state, holder, title)."""
    return {row[1]: row[1:] for row in rows_of(stdout) if row[0] == "TASK"}


class TestDerivedStatus:
    """status.sh - task state derived from git refs, with nothing stored."""

    def test_an_unclaimed_task_without_dependencies_is_ready(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        result = run_status(["--no-fetch"], cwd=dev)
        assert task_rows(result.stdout)["ingestion-001"][1] == "ready"

    def test_a_claimed_task_is_in_progress_and_names_its_holder(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        run_claim(["ingestion-001"], cwd=dev)

        row = task_rows(run_status([], cwd=dev).stdout)["ingestion-001"]

        assert row[1] == "in-progress"
        assert row[2] == "devA"

    def test_a_task_waiting_on_an_unfinished_dependency_is_blocked(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        write_task(dev, "ingestion-002", depends_on="ingestion-001")

        rows = task_rows(run_status(["--no-fetch"], cwd=dev).stdout)

        assert rows["ingestion-001"][1] == "ready"
        assert rows["ingestion-002"][1] == "blocked"

    def test_claiming_a_dependency_does_not_unblock_its_dependents(self, tmp_path: Path, origin: Path) -> None:
        """Only merged work unblocks a dependent; work in progress is not done."""
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        write_task(dev, "ingestion-002", depends_on="ingestion-001")
        run_claim(["ingestion-001"], cwd=dev)

        rows = task_rows(run_status([], cwd=dev).stdout)

        assert rows["ingestion-002"][1] == "blocked"

    def test_the_ready_filter_returns_only_ready_tasks(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        write_task(dev, "ingestion-002", depends_on="ingestion-001")

        rows = task_rows(run_status(["--no-fetch", "--ready"], cwd=dev).stdout)

        assert list(rows) == ["ingestion-001"]

    def test_the_summary_counts_every_task(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        write_task(dev, "ingestion-002", depends_on="ingestion-001")
        write_task(dev, "ingestion-003", depends_on="ingestion-001")

        summary = next(row for row in rows_of(run_status(["--no-fetch"], cwd=dev).stdout) if row[0] == "SUMMARY")

        assert "ready=1" in summary
        assert "blocked=2" in summary

    def test_a_pull_request_out_of_draft_is_in_review(self, tmp_path: Path, origin: Path) -> None:
        """In review is what is waiting on a person rather than on a lane."""
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        bin_dir = fake_gh(tmp_path, open_prs=[("ingestion-001", False)])

        rows = task_rows(run_status(["--no-fetch"], cwd=dev, bin_dir=bin_dir).stdout)

        assert rows["ingestion-001"][1] == "in-review"

    def test_a_draft_pull_request_is_still_in_progress(self, tmp_path: Path, origin: Path) -> None:
        """A lane drafts its pull request the moment it opens one.

        Counting a draft as in review would report every running lane as waiting
        on a reviewer, which is the opposite of the truth.
        """
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        run_claim(["ingestion-001"], cwd=dev)
        bin_dir = fake_gh(tmp_path, open_prs=[("ingestion-001", True)])

        rows = task_rows(run_status(["--no-fetch"], cwd=dev, bin_dir=bin_dir).stdout)

        assert rows["ingestion-001"][1] == "in-progress"

    def test_a_merged_task_outranks_its_open_pull_request(self, tmp_path: Path, origin: Path) -> None:
        """Stale open pull requests exist; merged is the end state."""
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        bin_dir = fake_gh(tmp_path, merged=["ingestion-001"], open_prs=[("ingestion-001", False)])

        rows = task_rows(run_status(["--no-fetch"], cwd=dev, bin_dir=bin_dir).stdout)

        assert rows["ingestion-001"][1] == "done"

    def test_a_task_merged_long_ago_with_its_branch_deleted_stays_done(self, tmp_path: Path, origin: Path) -> None:
        """Past the bulk query's window, with no branch left, it must not read as ready."""
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        write_task(dev, "ingestion-002", depends_on="ingestion-001")
        bin_dir = fake_gh(tmp_path, merged_long_ago=["ingestion-001"])

        rows = task_rows(run_status(["--no-fetch"], cwd=dev, bin_dir=bin_dir).stdout)

        assert rows["ingestion-001"][1] == "done"
        assert rows["ingestion-002"][1] == "ready"

    def test_dies_without_gh_rather_than_reporting_merged_work_as_ready(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        no_gh = tmp_path / "no-gh"
        no_gh.mkdir()
        for directory in os.environ["PATH"].split(os.pathsep):
            for tool in Path(directory).glob("*") if Path(directory).is_dir() else []:
                if tool.name != "gh" and not (no_gh / tool.name).exists():
                    (no_gh / tool.name).symlink_to(tool)

        result = run_status(["--no-fetch"], cwd=dev, path=str(no_gh))

        assert result.returncode == CLAIM_ERROR
        assert "gh not found" in result.stderr
        assert "TASK" not in result.stdout

    def test_dies_when_gh_cannot_list_pull_requests(self, tmp_path: Path, origin: Path) -> None:
        """An unauthenticated gh must not read as "nothing is merged"."""
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        bin_dir = tmp_path / "failing-gh"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        (bin_dir / "gh").chmod(0o755)

        result = run_status(["--no-fetch"], cwd=dev, bin_dir=bin_dir)

        assert result.returncode == CLAIM_ERROR
        assert "gh could not list pull requests" in result.stderr
        assert "TASK" not in result.stdout

    def test_dies_without_a_tasks_directory(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        assert run_status(["--no-fetch"], cwd=dev).returncode == CLAIM_ERROR


def run_snapshot(args: list[str], *, cwd: Path, bin_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir or fake_gh(cwd.parent)}{os.pathsep}{env['PATH']}"
    return subprocess.run(  # noqa: S603
        [SH, str(SCRIPTS_DIR / "snapshot.sh"), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
    )


def snapshot_of(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


DECOMPOSITION = """# Decomposition: shop

## Source

- `delivery/prd.md`

## Epics

### ingestion

Every source document is loaded, with "quoted" and \\ escaped text.
It spans two lines.

- `ingestion-001` - Do ingestion-001
- `ingestion-002` - Do ingestion-002

## Parallelism

**Run as:** lanes
"""


class TestSnapshot:
    """snapshot.sh - the one document connectors to external tools read (ADR-005)."""

    def test_is_versioned_valid_json_naming_the_use_case(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")

        snapshot = snapshot_of(run_snapshot(["--no-fetch"], cwd=dev))

        assert snapshot["schema"] == 1
        assert snapshot["use_case"]["repo"] == "devA"
        assert snapshot["use_case"]["commit"] == git(dev, "rev-parse", "HEAD").stdout.strip()

    def test_tasks_carry_their_derived_state_and_frontmatter(self, tmp_path: Path, origin: Path) -> None:
        """The state must be the one status.sh derives, or a connector and a person disagree."""
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        write_task(dev, "ingestion-002", depends_on="ingestion-001")
        run_claim(["ingestion-001"], cwd=dev)

        tasks = {t["id"]: t for t in snapshot_of(run_snapshot(["--no-fetch"], cwd=dev))["tasks"]}

        assert tasks["ingestion-001"]["state"] == "in-progress"
        assert tasks["ingestion-001"]["holder"] == "devA"
        assert tasks["ingestion-002"] == {
            "id": "ingestion-002",
            "title": "Do ingestion-002",
            "type": None,
            "epic": "ingestion",
            "repo": "devA",
            "state": "blocked",
            "holder": None,
            "depends_on": ["ingestion-001"],
            "pull_request": None,
            "file": "delivery/tasks/ingestion-002.md",
        }

    def test_a_title_keeps_its_commas_and_loses_its_quotes(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        task_file = dev / "delivery" / "tasks" / "ingestion-001.md"
        task_file.write_text(
            task_file.read_text(encoding="utf-8").replace(
                "title: Do ingestion-001", 'title: "Load HTML, Markdown and PDF"'
            ),
            encoding="utf-8",
        )

        task = snapshot_of(run_snapshot(["--no-fetch"], cwd=dev))["tasks"][0]

        assert task["title"] == "Load HTML, Markdown and PDF"

    def test_a_task_under_review_links_its_pull_request(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        url = "https://forge.example/org/devA/pull/42"
        bin_dir = fake_gh(tmp_path, open_prs=[("ingestion-001", False)], urls={"ingestion-001": url})

        task = snapshot_of(run_snapshot(["--no-fetch"], cwd=dev, bin_dir=bin_dir))["tasks"][0]

        assert task["state"] == "in-review"
        assert task["pull_request"] == url

    def test_epics_carry_what_they_deliver_from_the_decomposition(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        (dev / "delivery" / "decomposition.md").write_text(DECOMPOSITION, encoding="utf-8")

        epics = snapshot_of(run_snapshot(["--no-fetch"], cwd=dev))["epics"]

        assert epics == [
            {
                "id": "ingestion",
                "delivers": 'Every source document is loaded, with "quoted" and \\ escaped text. It spans two lines.',
            }
        ]

    def test_an_epic_missing_from_the_decomposition_still_appears(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")

        epics = snapshot_of(run_snapshot(["--no-fetch"], cwd=dev))["epics"]

        assert epics == [{"id": "ingestion", "delivers": None}]

    def test_lists_the_documents_a_reader_outside_git_needs(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        delivery = dev / "delivery"
        (delivery / "prd.md").write_text("# Shop requirements\n", encoding="utf-8")
        (delivery / "decomposition.md").write_text(DECOMPOSITION, encoding="utf-8")
        (delivery / "contracts").mkdir()
        (delivery / "contracts" / "search-api.md").write_text("# Search API\n", encoding="utf-8")
        (dev / "docs" / "adr").mkdir(parents=True)
        (dev / "docs" / "adr" / "ADR-001-storage.md").write_text("# ADR-001: Storage\n", encoding="utf-8")

        documents = snapshot_of(run_snapshot(["--no-fetch"], cwd=dev))["documents"]

        assert documents == [
            {"kind": "requirements", "path": "delivery/prd.md", "title": "Shop requirements"},
            {"kind": "decomposition", "path": "delivery/decomposition.md", "title": "Decomposition: shop"},
            {"kind": "decision", "path": "docs/adr/ADR-001-storage.md", "title": "ADR-001: Storage"},
            {"kind": "contract", "path": "delivery/contracts/search-api.md", "title": "Search API"},
        ]

    def test_fails_when_status_cannot_be_derived(self, tmp_path: Path, origin: Path) -> None:
        """A snapshot with guessed states would move Jira cards on a guess."""
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        bin_dir = tmp_path / "failing-gh"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        (bin_dir / "gh").chmod(0o755)

        result = run_snapshot(["--no-fetch"], cwd=dev, bin_dir=bin_dir)

        assert result.returncode == CLAIM_ERROR
        assert result.stdout == ""


PRD = """\
# Project

**Status:** approved

## Outcomes

- **A1.** One server serves one organisation.
- **A4.** Members sign in; revoking access takes effect at their next request.
- **R1.** Keyword search finds a note.
- **X1a.** A member never reaches a store they were not granted.
"""

PLAN = """\
# Decomposition: tiroir

**Status:** approved

## Milestones

### skeleton

**Exit:** a member finds a note they appended.
**Requirements:** A1, A4 (part),
  R1
**Epics:** server

### team

**Exit:** two members share a store.
**Requirements:** A4, X1a
**Epics:**

## Epics

### server

The server runs.

- `server-001` - Do server-001
- `server-002` - Do server-002
"""


def write_plan(repo: Path, *, plan: str = PLAN) -> None:
    (repo / "delivery").mkdir(exist_ok=True)
    (repo / "delivery" / "prd.md").write_text(PRD, encoding="utf-8")
    (repo / "delivery" / "decomposition.md").write_text(plan, encoding="utf-8")


def write_covering_task(repo: Path, task_id: str, covers: str, *, epic: str = "server") -> None:
    tasks = repo / "delivery" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    (tasks / f"{task_id}.md").write_text(
        f"---\nid: {task_id}\ntitle: Do {task_id}\nepic: {epic}\ndepends_on: []\nparallel: true\n"
        f"conflicts_with: []\ntier: build\n---\n\n## Covers\n\n{covers}\n\n## Acceptance criteria\n- observable\n",
        encoding="utf-8",
    )


def write_review(repo: Path, slug: str, status: str) -> None:
    folder = repo / "delivery" / "milestones"
    folder.mkdir(exist_ok=True)
    (folder / f"{slug}.md").write_text(f"# Milestone review: {slug}\n\n**Status:** {status}\n", encoding="utf-8")


def milestone_rows(stdout: str) -> list[list[str]]:
    return [row[1:] for row in rows_of(stdout) if row[0] == "MILESTONE"]


class TestMilestoneState:
    """status.sh - a milestone's state, derived from its tasks and its review note."""

    def test_a_plan_without_milestones_prints_no_milestone_row(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        (dev / "delivery" / "decomposition.md").write_text(DECOMPOSITION, encoding="utf-8")
        assert milestone_rows(run_status(["--no-fetch"], cwd=dev).stdout) == []

    def test_the_current_milestone_is_active_until_its_tasks_merge(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_plan(dev)
        write_covering_task(dev, "server-001", "- A1")
        write_covering_task(dev, "server-002", "- R1")
        result = run_status(["--no-fetch"], cwd=dev, bin_dir=fake_gh(tmp_path, merged=["server-001"]))
        assert milestone_rows(result.stdout) == [
            ["skeleton", "active", "server", "A1 A4 R1"],
            ["team", "planned", "-", "A4 X1a"],
        ]

    def test_merged_then_reviewing_then_closed(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_plan(dev)
        write_covering_task(dev, "server-001", "- A1")
        write_covering_task(dev, "server-002", "- R1")
        gh = fake_gh(tmp_path, merged=["server-001", "server-002"])

        def states() -> list[str]:
            return [row[1] for row in milestone_rows(run_status(["--no-fetch"], cwd=dev, bin_dir=gh).stdout)]

        assert states() == ["merged", "planned"]
        write_review(dev, "skeleton", "draft")
        assert states() == ["reviewing", "planned"]
        write_review(dev, "skeleton", "approved")
        assert states() == ["closed", "undecomposed"]

    def test_a_filter_prints_task_rows_only(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_plan(dev)
        write_covering_task(dev, "server-001", "- A1")
        assert milestone_rows(run_status(["--no-fetch", "--ready"], cwd=dev).stdout) == []


def run_coverage(args: list[str], *, cwd: Path, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return subprocess.run(  # noqa: S603
        [SH, str(SCRIPTS_DIR / "coverage.sh"), "--no-fetch", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        check=False,
    )


class TestCoverage:
    """coverage.sh - what merged work covers of each requirement."""

    def test_reports_each_requirement_with_the_tasks_behind_it(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_plan(dev)
        write_covering_task(dev, "server-001", "- A1\n- A4 (part): sign-in only;\n  revocation comes with team")
        write_covering_task(dev, "server-002", "- R1")
        result = run_coverage([], cwd=dev, bin_dir=fake_gh(tmp_path, merged=["server-001"]))
        assert result.returncode == 0, result.stderr
        assert rows_of(result.stdout) == [
            ["REQ", "A1", "covered", "skeleton", "server-001", "-"],
            ["REQ", "A4", "partly", "skeleton,team", "server-001", "-"],
            ["PART", "A4", "server-001", "done", "sign-in only; revocation comes with team"],
            ["REQ", "R1", "planned", "skeleton", "-", "server-002"],
            ["REQ", "X1a", "not-started", "team", "-", "-"],
            ["COVERAGE", "covered=1", "partly=1", "planned=1", "not-started=1"],
        ]

    def test_a_full_cover_merged_later_completes_a_partial_one(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_plan(dev)
        write_covering_task(dev, "server-001", "- A4 (part): sign-in only")
        write_covering_task(dev, "server-002", "- A4")
        result = run_coverage([], cwd=dev, bin_dir=fake_gh(tmp_path, merged=["server-001", "server-002"]))
        assert ["REQ", "A4", "covered", "skeleton,team", "server-001,server-002", "-"] in rows_of(result.stdout)
        assert [row for row in rows_of(result.stdout) if row[0] == "PART"] == []

    def test_a_milestone_narrows_the_report_to_its_targets(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_plan(dev)
        write_covering_task(dev, "server-001", "- A1")
        result = run_coverage(["--milestone", "team"], cwd=dev, bin_dir=fake_gh(tmp_path))
        assert [row[1] for row in rows_of(result.stdout) if row[0] == "REQ"] == ["A4", "X1a"]

    def test_an_unknown_milestone_is_an_error(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_plan(dev)
        write_covering_task(dev, "server-001", "- A1")
        result = run_coverage(["--milestone", "nope"], cwd=dev, bin_dir=fake_gh(tmp_path))
        assert result.returncode == 1
        assert "no milestone 'nope'" in result.stderr

    def test_requirements_without_ids_are_an_error(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        (dev / "delivery" / "prd.md").write_text("# P\n\n- one server\n", encoding="utf-8")
        result = run_coverage([], cwd=dev, bin_dir=fake_gh(tmp_path))
        assert result.returncode == 1
        assert "has no requirement ids" in result.stderr

    def test_fails_rather_than_guess_when_merged_state_cannot_be_read(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_plan(dev)
        write_covering_task(dev, "server-001", "- A1")
        bin_dir = tmp_path / "broken"
        bin_dir.mkdir()
        (bin_dir / "gh").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        (bin_dir / "gh").chmod(0o755)
        result = run_coverage([], cwd=dev, bin_dir=bin_dir)
        assert result.returncode == 1
        assert "REQ" not in result.stdout


class TestSnapshotMilestones:
    """snapshot.sh - milestones and requirement coverage, for connectors."""

    def test_carries_milestones_and_coverage(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_plan(dev)
        write_covering_task(dev, "server-001", "- A1\n- A4 (part): sign-in only")
        write_covering_task(dev, "server-002", "- R1")

        snapshot = snapshot_of(run_snapshot(["--no-fetch"], cwd=dev, bin_dir=fake_gh(tmp_path, merged=["server-001"])))

        assert snapshot["schema"] == 1
        assert snapshot["milestones"] == [
            {
                "id": "skeleton",
                "state": "active",
                "exit": "a member finds a note they appended.",
                "epics": ["server"],
                "requirements": ["A1", "A4", "R1"],
            },
            {
                "id": "team",
                "state": "planned",
                "exit": "two members share a store.",
                "epics": [],
                "requirements": ["A4", "X1a"],
            },
        ]
        assert snapshot["requirements"] == [
            {
                "id": "A1",
                "state": "covered",
                "milestones": ["skeleton"],
                "merged": ["server-001"],
                "open": [],
                "parts": [],
            },
            {
                "id": "A4",
                "state": "partly",
                "milestones": ["skeleton", "team"],
                "merged": ["server-001"],
                "open": [],
                "parts": [{"task": "server-001", "state": "done", "note": "sign-in only"}],
            },
            {
                "id": "R1",
                "state": "planned",
                "milestones": ["skeleton"],
                "merged": [],
                "open": ["server-002"],
                "parts": [],
            },
            {"id": "X1a", "state": "not-started", "milestones": ["team"], "merged": [], "open": [], "parts": []},
        ]

    def test_a_project_without_them_has_empty_lists(self, tmp_path: Path, origin: Path) -> None:
        dev = developer(tmp_path, origin, "devA")
        write_task(dev, "ingestion-001")
        (dev / "delivery" / "prd.md").write_text("# Shop requirements\n\n- loads documents\n", encoding="utf-8")

        snapshot = snapshot_of(run_snapshot(["--no-fetch"], cwd=dev))

        assert snapshot["milestones"] == []
        assert snapshot["requirements"] == []
