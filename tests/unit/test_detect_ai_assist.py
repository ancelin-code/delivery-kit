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
    # Given a commit ending with an agent's trailer
    commits = f"fix: a thing\n\nBody text.\n\n{trailer}\n"

    # When the detector reads it
    result = detect(commits)

    # Then the pull request is assisted, because of the trailer
    assert result.returncode == YES
    assert "trailer" in result.stdout


def test_any_commit_of_several_can_carry_the_trailer() -> None:
    # Given three commits, only the second with an agent trailer
    commits = "feat: one\n\nplain\nfix: two\n\nCo-Authored-By: Claude <noreply@anthropic.com>\nchore: three\n"

    # When the detector reads them
    result = detect(commits)

    # Then the pull request is assisted
    assert result.returncode == YES


def test_a_human_co_author_does_not_count() -> None:
    # Given a commit co-authored by a person
    commits = "fix: it\n\nCo-authored-by: Sam Doe <sam@example.com>\n"

    # When the detector reads it
    result = detect(commits)

    # Then the pull request is not assisted
    assert result.returncode == NO


def test_merely_mentioning_a_tool_is_not_a_signal() -> None:
    # Given a commit that names agents in its text, not in a trailer
    commits = "docs: compare with Claude Code and Copilot CLI\n\nCodex is also supported.\n"

    # When the detector reads it
    result = detect(commits)

    # Then the pull request is not assisted
    assert result.returncode == NO


def test_no_commits_and_nothing_else_is_not_assisted() -> None:
    # When the detector reads no commits from a human author
    result = detect()

    # Then the pull request is not assisted
    assert result.returncode == NO


@pytest.mark.parametrize("author", ["Copilot", "copilot-swe-agent[bot]", "app/copilot-swe-agent", "claude[bot]"])
def test_an_agents_own_account_counts(author: str) -> None:
    # When an agent's account opened the pull request
    result = detect("fix: it\n", author=author)

    # Then it is assisted, because of the account
    assert result.returncode == YES
    assert "account" in result.stdout


@pytest.mark.parametrize("author", ["dependabot[bot]", "ancelin-code", "github-actions[bot]"])
def test_other_accounts_do_not_count(author: str) -> None:
    # When a person or a non-agent bot opened the pull request
    result = detect("fix: it\n", author=author)

    # Then it is not assisted
    assert result.returncode == NO
