from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

# The shell that runs the helpers under test. POSIX sh is the contract, so CI
# sets this to dash, BusyBox ash and a bash in sh mode in turn.
SH = os.environ.get("ALULA_TEST_SH", "sh")
