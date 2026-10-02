"""The detector labels agent work from commit trailers or an agent's own account."""

import subprocess

import pytest

from tests.conftest import PROJECT_DIR

SCRIPT = PROJECT_DIR / ".mise" / "scripts" / "detect-ai-assist"

YES = 0
NO = 1


def detect(commits: str = "", *, author: str = "someone") -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607
        input=commits,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "PR_AUTHOR": author},
    )


@pytest.mark.parametrize(
    "trailer",
    [
        "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>",
        "co-authored-by: Copilot <copilot@users.noreply.github.com>",
        "Co-authored-by: Codex <codex@openai.com>",
        "Assisted-by: Gemini CLI",
        "Generated-by: opencode",
    ],
)
def test_an_agent_trailer_counts(trailer: str) -> None:
    result = detect(f"fix: a thing\n\nBody text.\n\n{trailer}\n")
    assert result.returncode == YES
    assert "trailer" in result.stdout


def test_any_commit_of_several_can_carry_the_trailer() -> None:
    commits = "feat: one\n\nplain\nfix: two\n\nCo-Authored-By: Claude <noreply@anthropic.com>\nchore: three\n"
    assert detect(commits).returncode == YES


def test_a_human_co_author_does_not_count() -> None:
    assert detect("fix: it\n\nCo-authored-by: Sam Doe <sam@example.com>\n").returncode == NO


def test_merely_mentioning_a_tool_is_not_a_signal() -> None:
    commits = "docs: compare with Claude Code and Copilot CLI\n\nCodex is also supported.\n"
    assert detect(commits).returncode == NO


def test_no_commits_and_nothing_else_is_not_assisted() -> None:
    assert detect().returncode == NO


@pytest.mark.parametrize("author", ["Copilot", "copilot-swe-agent[bot]", "app/copilot-swe-agent", "claude[bot]"])
def test_an_agents_own_account_counts(author: str) -> None:
    result = detect("fix: it\n", author=author)
    assert result.returncode == YES
    assert "account" in result.stdout


@pytest.mark.parametrize("author", ["dependabot[bot]", "ancelin-code", "github-actions[bot]"])
def test_other_accounts_do_not_count(author: str) -> None:
    assert detect("fix: it\n", author=author).returncode == NO
