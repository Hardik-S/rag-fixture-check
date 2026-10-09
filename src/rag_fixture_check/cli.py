"""Command-line interface for offline RAG fixture validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import validator


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rag-fixture-check",
        description="Check fixture IDs and exact source spans without model or network access.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify", help="validate source and case JSONL files")
    verify.add_argument("sources", type=Path, metavar="SOURCES.jsonl")
    verify.add_argument("cases", type=Path, metavar="CASES.jsonl")
    verify.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def _safe_result(result: dict[str, Any]) -> dict[str, Any]:
    """Project validator output onto the documented, content-free CLI schema."""
    diagnostics = []
    for diagnostic in result.get("diagnostics", []):
        diagnostics.append(
            {
                "file": diagnostic.get("file"),
                "line": diagnostic.get("line"),
                "case_id": diagnostic.get("case_id"),
                "source_id": diagnostic.get("source_id"),
                "code": diagnostic.get("code"),
                "message": diagnostic.get("message"),
            }
        )
    return {
        "valid": bool(result.get("valid", False)),
        "source_count": result.get("source_count", 0),
        "case_count": result.get("case_count", 0),
        "citation_count": result.get("citation_count", 0),
        "diagnostics": diagnostics,
    }


def _render_text(result: dict[str, Any]) -> str:
    state = "valid" if result["valid"] else "invalid"
    lines = [
        f"Fixture check: {state}",
        "Sources: {source_count}; cases: {case_count}; citations: {citation_count}".format(**result),
    ]
    for item in result["diagnostics"]:
        location = item["file"] or "input"
        if item["line"] is not None:
            location += f":{item['line']}"
        identifiers = []
        if item["case_id"] is not None:
            identifiers.append(f"case={item['case_id']}")
        if item["source_id"] is not None:
            identifiers.append(f"source={item['source_id']}")
        suffix = f" ({', '.join(identifiers)})" if identifiers else ""
        lines.append(f"{location}: {item['code']}: {item['message']}{suffix}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        raw = validator.validate_files(args.sources, args.cases)
        result = _safe_result(raw)
    except (OSError, UnicodeError, ValueError, TypeError):
        # Never expose parser exception text: it can contain untrusted input.
        result = {
            "valid": False,
            "source_count": 0,
            "case_count": 0,
            "citation_count": 0,
            "diagnostics": [
                {
                    "file": None,
                    "line": None,
                    "case_id": None,
                    "source_id": None,
                    "code": "input_error",
                    "message": "Unable to read or validate input files.",
                }
            ],
        }

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        print(_render_text(result))
    return 0 if result["valid"] else 2


if __name__ == "__main__":  # pragma: no cover - equivalent to the console entry point
    sys.exit(main())
