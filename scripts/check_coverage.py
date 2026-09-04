"""Enforce reviewed statement/branch floors on the canonical Linux coverage run."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Conservative floors from the full-suite baseline, not a claim of completeness.
FLOORS = {
    "total": (90, 79),
    "src/aselenium/manager/_http.py": (89, 79),
    "src/aselenium/manager/_cache.py": (87, 73),
    "src/aselenium/manager/_installation.py": (86, 82),
    "src/aselenium/connection.py": (92, 85),
    "src/aselenium/service.py": (73, 60),
    "src/aselenium/webdriver.py": (83, 60),
}


def check(data: Mapping[str, Any]) -> list[str]:
    """Find missing branch data or coverage below a critical-component floor.

    Args:
        data: JSON object emitted by coverage.py with branch coverage enabled.

    Returns:
        Actionable diagnostics, empty when every required component meets its floor.
    """
    issues = []
    files = {
        name.replace("\\", "/"): value for name, value in data.get("files", {}).items()
    }
    for name, floors in FLOORS.items():
        summary = (
            data.get("totals", {})
            if name == "total"
            else files.get(name, {}).get("summary", {})
        )
        for covered_key, total_key, floor in (
            ("covered_lines", "num_statements", floors[0]),
            ("covered_branches", "num_branches", floors[1]),
        ):
            covered, total = summary.get(covered_key), summary.get(total_key)
            if (
                type(covered) is not int
                or type(total) is not int
                or not 0 <= covered <= total
                or total <= 0
            ):
                issues.append(f"{name}: missing or invalid {covered_key}/{total_key}")
                continue
            percentage = 100 * covered / total
            if percentage < floor:
                issues.append(
                    f"{name}: {covered_key} {percentage:.2f}% is below {floor}%"
                )
    return issues


def main(argv: Sequence[str] | None = None) -> int:
    """Read a full-suite coverage JSON report and enforce reviewed floors.

    Args:
        argv: CLI arguments; None reads the process command line.

    Returns:
        Zero when the coverage contract passes, one otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    issues = check(json.loads(args.report.read_text(encoding="utf-8")))
    print(json.dumps({"floors": FLOORS, "issues": issues}, indent=2))
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
