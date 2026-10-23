"""The release check ties a tag to every place a version is written."""

import re
import subprocess
from pathlib import Path

import pytest

from tests.conftest import PROJECT_DIR

SCRIPT = PROJECT_DIR / ".mise" / "scripts" / "check-release"

OK = 0
FAILED = 1
USAGE = 2
TWO_PROBLEMS = 2


def make_repo(root: Path, *, skill: str = "0.1.0", pyproject: str = "0.1.0") -> None:
    skill_dir = root / ".agents" / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(f'---\nname: demo\nversion: "{skill}"\n---\n')
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{pyproject}"\n')
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-10-02\n\n"
        "- First release.\n- Second line.\n\n## [0.0.9] - 2026-09-01\n\n- Older.\n"
    )


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        env={"CHECK_RELEASE_ROOT": str(root), "PATH": "/usr/bin:/bin"},
    )


def test_consistent_repository_passes(tmp_path: Path) -> None:
    # Given a repository at 0.1.0 everywhere
    make_repo(tmp_path)

    # When v0.1.0 is checked
    result = run(tmp_path, "v0.1.0")

    # Then it passes
    assert result.returncode == OK


def test_notes_are_the_matching_section_only(tmp_path: Path) -> None:
    # Given a changelog with a section before and after 0.1.0
    make_repo(tmp_path)

    # When the notes for v0.1.0 are asked for
    result = run(tmp_path, "v0.1.0", "--notes")

    # Then only that section's body comes back
    assert result.returncode == OK
    assert result.stdout.strip() == "- First release.\n- Second line."


@pytest.mark.parametrize("tag", ["0.1.0", "v1", "v0.1", "v0.1.0-rc1", ""])
def test_malformed_tag_is_a_usage_error(tmp_path: Path, tag: str) -> None:
    # Given a consistent repository
    make_repo(tmp_path)

    # When a tag that is not vX.Y.Z is checked
    result = run(tmp_path, tag)

    # Then it is a usage error
    assert result.returncode == USAGE


def test_skill_version_mismatch_fails(tmp_path: Path) -> None:
    # Given a skill left at another version
    make_repo(tmp_path, skill="0.2.0")

    # When v0.1.0 is checked
    result = run(tmp_path, "v0.1.0")

    # Then it fails, naming the skill's version
    assert result.returncode == FAILED
    assert "SKILL.md has version '0.2.0'" in result.stderr


def test_pyproject_version_mismatch_fails(tmp_path: Path) -> None:
    # Given pyproject.toml left at another version
    make_repo(tmp_path, pyproject="0.0.9")

    # When v0.1.0 is checked
    result = run(tmp_path, "v0.1.0")

    # Then it fails, naming pyproject's version
    assert result.returncode == FAILED
    assert "pyproject.toml has version '0.0.9'" in result.stderr


def test_missing_changelog_section_fails(tmp_path: Path) -> None:
    # Given a changelog with no 0.2.0 section
    make_repo(tmp_path)

    # When v0.2.0 is checked
    result = run(tmp_path, "v0.2.0")

    # Then it fails on the missing section
    assert result.returncode == FAILED
    assert "no filled '## [0.2.0]' section" in result.stderr


def test_every_problem_is_reported_in_one_run(tmp_path: Path) -> None:
    # Given a skill and pyproject both at another version
    make_repo(tmp_path, skill="0.3.0", pyproject="0.3.0")

    # When v0.1.0 is checked
    result = run(tmp_path, "v0.1.0")

    # Then both problems are reported, not just the first
    assert result.stderr.count("ERROR:") == TWO_PROBLEMS


def test_the_real_repository_agrees_with_its_own_version() -> None:
    """Skills, pyproject and changelog must move together, whatever the number."""
    # Given the version this repository's pyproject declares
    pyproject = (PROJECT_DIR / "pyproject.toml").read_text()
    match = re.search(r'^version = "(.+)"$', pyproject, re.MULTILINE)
    assert match

    # When that version's tag is checked against the repository itself
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), f"v{match.group(1)}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )

    # Then it passes
    assert result.returncode == OK, result.stderr
