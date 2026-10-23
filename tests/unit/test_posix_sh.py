"""The helpers are POSIX sh, so they run wherever a developer has git and sh.

ShellCheck reads the shebang and holds a `#!/bin/sh` script to POSIX, so
`mise run lint` rejects a bashism. These tests keep that check from being
dodged: a helper that declared bash would escape it.
"""

import pytest

from tests.conftest import PROJECT_DIR

EXPECTED_HELPERS = 14
SCRIPTS = sorted(PROJECT_DIR.glob(".agents/skills/*/scripts/*.sh"))
EXECUTABLES = [path for path in SCRIPTS if path.name != "harness.sh"]


def test_helpers_were_found() -> None:
    # When the helpers are collected from every skill's scripts directory
    found = len(SCRIPTS)

    # Then none was renamed out of the glob
    assert found == EXPECTED_HELPERS


@pytest.mark.parametrize("script", EXECUTABLES, ids=lambda p: p.name)
def test_a_helper_declares_posix_sh(script) -> None:
    # When its header is read
    lines = script.read_text().splitlines()

    # Then it declares POSIX sh and strict mode
    assert lines[0] == "#!/bin/sh"
    assert lines[1] == "set -eu"


def test_the_adapters_are_linted_as_sh() -> None:
    """harness.sh is sourced, so it has no shebang to tell ShellCheck its dialect."""
    # When the sourced adapters are read
    text = PROJECT_DIR.joinpath(".agents/skills/delivery-orchestrator/scripts/harness.sh").read_text()

    # Then their first line names the dialect instead
    assert text.startswith("# shellcheck shell=sh\n")
