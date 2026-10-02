"""Read the model labels table out of the delivery conventions.

The conventions are the single place a label's meaning is written down. Two
scripts must nevertheless agree with it in code: ``validate-tasks.sh`` accepts
or rejects a label, and ``launch-lanes.sh`` routes one to a harness. Neither can
read prose, so the copies are unavoidable.

Parsing the table here makes them checkable instead. A label added to the
conventions and to only one of the scripts now fails a test, rather than
surfacing when a lane refuses to start or starts on the wrong side of the
budget.
"""

from __future__ import annotations

import re
from pathlib import Path

CONVENTIONS = (
    Path(__file__).resolve().parents[2]
    / ".agents"
    / "skills"
    / "fourmee"
    / "references"
    / "conventions.md"
)

HARNESS_BY_NAME = {"Claude Code": "claude", "Copilot CLI": "copilot"}

_ROW = re.compile(r"^\|\s*`(?P<label>[a-z0-9-]+)`\s*\|[^|]*\|\s*(?P<harness>[^|]+?)\s*\|\s*$")


def _table() -> dict[str, str]:
    """Map each documented label to the harness column's short name."""
    labels: dict[str, str] = {}
    in_section = False
    for line in CONVENTIONS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = line.strip() == "## Model labels"
            continue
        if not in_section:
            continue
        match = _ROW.match(line)
        if match is None:
            continue
        harness = match["harness"]
        if harness not in HARNESS_BY_NAME:
            message = f"unknown harness {harness!r} in the model labels table"
            raise AssertionError(message)
        labels[match["label"]] = HARNESS_BY_NAME[harness]
    if not labels:
        message = f"no model labels parsed from {CONVENTIONS}"
        raise AssertionError(message)
    return labels


ROUTING = _table()
LABELS = sorted(ROUTING)


def _efforts() -> list[str]:
    """The effort levels the conventions offer, from the level table.

    The row for the rare levels names two in one cell, so the labels are pulled
    from the code spans rather than from the cell.
    """
    levels: list[str] = []
    in_section = False
    for line in CONVENTIONS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = line.strip() == "## Model labels"
            continue
        if not in_section or not line.startswith("| `"):
            continue
        levels.extend(
            name for name in re.findall(r"`([a-z]+)`", line.split("|")[1]) if name not in ROUTING
        )
    if not levels:
        message = f"no effort levels parsed from {CONVENTIONS}"
        raise AssertionError(message)
    return levels


EFFORTS = _efforts()
