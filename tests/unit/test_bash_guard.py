"""Every helper refuses an old bash with one clear line.

macOS ships bash 3.2, and without a guard a helper dies halfway through on
syntax it cannot parse. The static test keeps the guard in every helper; the
behavioural test runs it for real wherever the system bash is too old, which
is the case on the macOS CI job.
"""

import re
import subprocess
from pathlib import Path

import pytest

from tests.conftest import PROJECT_DIR

EXPECTED_HELPERS = 12
FAILED = 1
HELPERS = sorted(PROJECT_DIR.glob(".agents/skills/*/scripts/*.sh"))
SYSTEM_BASH = Path("/bin/bash")


def system_bash_version() -> tuple[int, int] | None:
    if not SYSTEM_BASH.exists():
        return None
    out = subprocess.run(  # noqa: S603
        [str(SYSTEM_BASH), "-c", "echo ${BASH_VERSINFO[0]}.${BASH_VERSINFO[1]}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    major, minor = out.split(".")
    return int(major), int(minor)


def test_helpers_were_found() -> None:
    assert len(HELPERS) == EXPECTED_HELPERS


@pytest.mark.parametrize("helper", HELPERS, ids=lambda p: p.name)
def test_guard_comes_before_any_real_work(helper: Path) -> None:
    head = "\n".join(helper.read_text().splitlines()[:10])
    assert "BASH_VERSINFO[0] < 4" in head
    assert re.search(r"BASH_VERSINFO\[1\] < 4", head)


@pytest.mark.skipif(
    (system_bash_version() or (99, 0)) >= (4, 4),
    reason="the system bash is already 4.4 or later",
)
@pytest.mark.parametrize("helper", HELPERS, ids=lambda p: p.name)
def test_old_bash_gets_a_clear_error(helper: Path) -> None:
    result = subprocess.run(  # noqa: S603
        [str(SYSTEM_BASH), str(helper)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == FAILED
    assert result.stderr.startswith("ERROR\tbash 4.4 or later is required")
