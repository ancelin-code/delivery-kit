"""Read the tiers out of the delivery conventions.

The conventions are the single place a tier's meaning is written down. Two
scripts must nevertheless agree with it in code: ``validate-tasks.sh`` accepts
or rejects a tier, and ``launch-lanes.sh`` knows which ones it may route.
Neither can read prose, so the copies are unavoidable.

Parsing the tables here makes them checkable instead. A tier added to the
conventions and to only one of the scripts now fails a test, rather than
surfacing when a lane refuses to start.
"""

from __future__ import annotations

import re
from pathlib import Path

CONVENTIONS = (
    Path(__file__).resolve().parents[2]
    / ".agents"
    / "skills"
    / "delivery-orchestrator"
    / "references"
    / "conventions.md"
)

_ROW = re.compile(r"^\|\s*(?P<first>[^|]+?)\s*\|")


def _first_cells(header: str) -> list[str]:
    """The code spans in the first column of the table whose header starts with ``header``."""
    cells: list[str] = []
    in_section = False
    in_table = False
    for line in CONVENTIONS.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            in_section = line.strip() == "## Tiers"
            in_table = False
            continue
        if not in_section:
            continue
        if line.startswith("|"):
            match = _ROW.match(line)
            first = match["first"] if match else ""
            if first == header:
                in_table = True
            elif in_table and not first.startswith("---"):
                cells.extend(re.findall(r"`([a-z]+)`", first))
        else:
            in_table = False
    if not cells:
        message = f"no '{header}' table parsed from {CONVENTIONS}"
        raise AssertionError(message)
    return cells


TIERS = _first_cells("Tier")
