#!/usr/bin/env python3
"""Summarize one polaris-python cloud E2E run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def newest_summary(root: Path) -> Path | None:
    candidates = [
        path
        for path in root.rglob("summary.json")
        if "verify-e2e-summary" in path.parent.name
    ]
    if not candidates:
        candidates = list(root.rglob("summary.json"))
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def summarize(root: Path) -> tuple[int, str]:
    root = root.resolve()
    manifest = load_json(root / "manifest.json")
    summary_path = newest_summary(root)
    lines = [
        "# Polaris Python Cloud E2E Result",
        "",
        f"- Run directory: {root}",
        f"- Run ID: {manifest.get('run_id', '<unknown>')}",
        f"- Package: {manifest.get('package', '<unknown>')}",
        f"- Server: {manifest.get('server', '<unknown>')}",
        f"- Namespace: {manifest.get('namespace', '<unknown>')}",
        f"- Started: {manifest.get('started_at', '<unknown>')}",
        f"- Finished: {manifest.get('finished_at', '<unknown>')}",
        f"- Exit code: {manifest.get('exit_code', '<unknown>')}",
    ]
    if summary_path is None:
        lines.extend([
            "",
            "No E2E summary.json was found. Inspect run.log and the logs/ directory.",
        ])
        return 0, "\n".join(lines) + "\n"

    summary = load_json(summary_path)
    passed = int(summary.get("passed", 0))
    failed = int(summary.get("failed", 0))
    lines.extend([
        "",
        f"Result: {passed} passed, {failed} failed",
        f"Summary: {summary_path.relative_to(root)}",
        "",
        "| Scenario | Code |",
        "| --- | ---: |",
    ])
    for item in summary.get("results", []):
        if isinstance(item, dict):
            lines.append(
                f"| {item.get('scenario', '<unknown>')} | "
                f"{item.get('code', '<unknown>')} |"
            )
    failures = [
        str(item.get("scenario"))
        for item in summary.get("results", [])
        if isinstance(item, dict) and item.get("code") != 0
    ]
    if failures:
        lines.extend(["", f"Failed scenarios: {', '.join(failures)}"])
    lines.extend([
        "",
        "Inspect order: result.json -> verification.log -> console.log -> polaris/log/.",
    ])
    return (1 if failed else 0), "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_directory", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        help="write the analysis to this file (default: RUN/analysis.txt)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return non-zero when the suite contains failed scenarios",
    )
    args = parser.parse_args()
    result, text = summarize(args.run_directory)
    output = args.output or args.run_directory / "analysis.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(text, end="")
    return result if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
