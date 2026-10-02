from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SKILLS_ROOT = Path(".agents/skills")
REPORT_DIR = Path("reports/lint/skill-scanner")
POLICY_PATH = ".skill-scanner-policy.yaml"
GIT = shutil.which("git")
LLM_ENV_VARS = (
    "SKILL_SCANNER_LLM_MODEL",
    "SKILL_SCANNER_LLM_API_KEY",
    "SKILL_SCANNER_LLM_BASE_URL",
    "SKILL_SCANNER_LLM_API_VERSION",
)
BLOCKING_SEVERITIES = {"CRITICAL", "HIGH"}


@dataclass(frozen=True)
class Scan:
    skill: Path
    report: Path
    returncode: int
    payload: dict[str, Any] | None
    output: str


def git_paths(*args: str) -> set[str]:
    result = subprocess.run(  # noqa: S603 - Git path and arguments are passed without a shell.
        [GIT, *args],
        check=True,
        capture_output=True,
    )
    return {path.decode().strip() for path in result.stdout.split(b"\0") if path}


def git_text(*args: str) -> str | None:
    result = subprocess.run(  # noqa: S603 - Git path and arguments are passed without a shell.
        [GIT, *args], check=False, capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def default_base() -> str | None:
    origin_head = git_text("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    for candidate in (origin_head, "origin/master", "origin/main", "@{upstream}"):
        if candidate and git_text("rev-parse", "--verify", "--quiet", candidate):
            return candidate
    return git_text("rev-parse", "--verify", "--quiet", "HEAD^")


def changed_paths(base: str | None) -> set[str]:
    paths: set[str] = set()
    if base:
        if not git_text("rev-parse", "--verify", "--quiet", base):
            raise ValueError(base)
        paths.update(git_paths("diff", "--name-only", "-z", f"{base}...HEAD", "--"))
    paths.update(git_paths("diff", "--cached", "--name-only", "-z", "--"))
    paths.update(git_paths("diff", "--name-only", "-z", "--"))
    paths.update(git_paths("ls-files", "--others", "--exclude-standard", "-z", "--"))
    return paths


def changed_skill_directories(paths: set[str]) -> list[Path]:
    root_parts = SKILLS_ROOT.parts
    skills = {
        SKILLS_ROOT / parts[len(root_parts)]
        for path in paths
        if len(parts := Path(path).parts) > len(root_parts) and parts[: len(root_parts)] == root_parts
    }
    return sorted(skill for skill in skills if (skill / "SKILL.md").is_file())


def all_skill_directories() -> list[Path]:
    return sorted(path.parent for path in SKILLS_ROOT.glob("*/SKILL.md"))


def scan_skill(skill: Path, *, use_llm: bool) -> Scan:
    report = REPORT_DIR / f"{skill.name}.json"
    command = [
        "skill-scanner",
        "scan",
        str(skill),
        "--fail-on-severity",
        "high",
        "--format",
        "json",
        "--output-json",
        str(report),
    ]
    if use_llm:
        command.extend(["--use-llm", "--enable-meta", "--policy", POLICY_PATH])

    result = subprocess.run(  # noqa: S603 - The scanner command is constructed above and never uses a shell.
        command, check=False, capture_output=True, text=True
    )
    output = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        payload = None
    return Scan(skill, report, result.returncode, payload, output)


def escape_command(value: object, *, property_value: bool = False) -> str:
    escaped = str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if property_value:
        escaped = escaped.replace(":", "%3A").replace(",", "%2C")
    return escaped


def finding_path(skill: Path, finding: dict[str, Any]) -> str:
    raw_path = finding.get("file_path")
    if not raw_path:
        return str(skill / "SKILL.md")
    path = Path(str(raw_path))
    if path.is_absolute():
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return str(path)
    if path.parts[:3] == skill.parts[:3]:
        return str(path)
    return str(skill / path)


def report_scan(scan: Scan) -> bool:
    if scan.returncode not in {0, 1} or scan.payload is None:
        print(f"{scan.skill.name}: skill-scanner failed", file=sys.stderr)
        if scan.output:
            print(scan.output, file=sys.stderr)
        elif scan.payload is None:
            print(f"No valid JSON report was written to {scan.report}.", file=sys.stderr)
        return False

    findings = scan.payload.get("findings", [])
    findings = findings if isinstance(findings, list) else []
    max_severity = str(scan.payload.get("max_severity", "UNKNOWN"))
    analyzers = scan.payload.get("analyzers_used", [])
    analyzers = analyzers if isinstance(analyzers, list) else []
    mode = "llm+meta" if {"llm_analyzer", "meta_analyzer"} <= set(analyzers) else "static"
    print(f"{scan.skill.name}: {len(findings)} finding(s), max severity {max_severity} ({mode})")

    blocking = False
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity", "UNKNOWN")).upper()
        blocking |= severity in BLOCKING_SEVERITIES
        if os.environ.get("GITHUB_ACTIONS") != "true":
            continue
        command = "error" if severity in BLOCKING_SEVERITIES else "warning"
        path = escape_command(finding_path(scan.skill, finding), property_value=True)
        title = escape_command(
            f"skill-scanner {finding.get('rule_id', severity)}",
            property_value=True,
        )
        message = escape_command(finding.get("description") or finding.get("title") or "Security finding")
        line = finding.get("line_number")
        line_property = f",line={line}" if isinstance(line, int) and line > 0 else ""
        print(f"::{command} file={path}{line_property},title={title}::{message}")
    return not blocking and scan.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan changed skills in parallel.")
    parser.add_argument("--all", action="store_true", help="scan every skill instead of changed skills")
    args = parser.parse_args()

    if GIT is None:
        print("git is required to select skills for scanning.", file=sys.stderr)
        return 1

    try:
        base = None if args.all else os.environ.get("SKILL_SCAN_BASE") or default_base()
        paths = set() if args.all else changed_paths(base)
    except ValueError as error:
        print(f"SKILL_SCAN_BASE does not resolve to a commit: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"Unable to select skills for scanning: {error}", file=sys.stderr)
        return 1

    skills = all_skill_directories() if args.all else changed_skill_directories(paths)
    if not skills:
        print("No changed skills to scan.")
        return 0

    configured = [name for name in LLM_ENV_VARS if os.environ.get(name)]
    missing = [name for name in LLM_ENV_VARS if not os.environ.get(name)]
    if configured and missing:
        print(
            "Skill scanner LLM mode requires all of " + ", ".join(LLM_ENV_VARS) + "; missing " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    shutil.rmtree(REPORT_DIR, ignore_errors=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    requested_jobs = int(os.environ.get("SKILL_SCAN_JOBS", "4"))
    jobs = max(1, min(requested_jobs, len(skills)))
    scope = "all" if args.all else "changed"
    print(f"Scanning {len(skills)} skill(s) ({scope}) with {jobs} parallel worker(s).")

    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        scans = list(executor.map(lambda skill: scan_skill(skill, use_llm=not missing), skills))

    results = [report_scan(scan) for scan in scans]
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
