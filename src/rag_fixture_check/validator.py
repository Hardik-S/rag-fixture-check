"""Strict, offline validation for RAG fixture JSONL files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SOURCE_KEYS = {"source_id", "text"}
_CASE_KEYS = {"case_id", "question", "answer", "citations"}
_CITATION_KEYS = {"source_id", "start", "end", "quote"}


class _InvalidJSON(ValueError):
    """Internal parse failure whose message never contains input data."""


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _InvalidJSON
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise _InvalidJSON


def _diagnostic(
    file: str,
    line: int,
    code: str,
    message: str,
    *,
    case_id: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    return {
        "file": file,
        "line": line,
        "case_id": case_id,
        "source_id": source_id,
        "code": code,
        "message": message,
    }


def _read_jsonl(path: Path, file_label: str, diagnostics: list[dict[str, Any]]) -> list[tuple[int, Any]]:
    try:
        raw = path.read_bytes()
    except OSError:
        diagnostics.append(_diagnostic(file_label, 1, "read_error", "Unable to read input file."))
        return []

    try:
        content = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        line = raw[: exc.start].count(b"\n") + 1
        diagnostics.append(_diagnostic(file_label, line, "invalid_utf8", "Input is not valid UTF-8."))
        return []

    rows: list[tuple[int, Any]] = []
    # JSONL records are separated by LF. `str.splitlines()` also treats valid
    # Unicode separators inside JSON strings as record boundaries.
    lines = content.split("\n")
    if lines and lines[-1] == "" and content.endswith("\n"):
        lines.pop()  # A conventional final newline does not add an empty JSONL row.
    for line_number, line in enumerate(lines, 1):
        if line.endswith("\r"):
            line = line[:-1]
        if not line.strip():
            diagnostics.append(_diagnostic(file_label, line_number, "blank_line", "Each line must contain one JSON value."))
            continue
        try:
            value = json.loads(
                line,
                object_pairs_hook=_pairs_no_duplicates,
                parse_constant=_reject_constant,
            )
        except (json.JSONDecodeError, _InvalidJSON, ValueError):
            diagnostics.append(_diagnostic(file_label, line_number, "invalid_json", "Line is not strict valid JSON."))
            continue
        rows.append((line_number, value))
    return rows


def _has_exact_keys(value: Any, expected: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == expected


def validate_files(sources_path: Path, cases_path: Path) -> dict:
    """Validate fixture files and return stable counts plus privacy-safe diagnostics."""
    diagnostics: list[dict[str, Any]] = []
    sources_rows = _read_jsonl(Path(sources_path), "sources", diagnostics)
    cases_rows = _read_jsonl(Path(cases_path), "cases", diagnostics)

    sources: dict[str, str] = {}
    seen_source_ids: set[str] = set()
    for line, value in sources_rows:
        if not _has_exact_keys(value, _SOURCE_KEYS):
            diagnostics.append(_diagnostic("sources", line, "schema_error", "Source row must have exactly the required fields."))
            continue
        source_id, source_text = value["source_id"], value["text"]
        if not isinstance(source_id, str) or not source_id.strip():
            diagnostics.append(_diagnostic("sources", line, "invalid_id", "Source ID must be a nonempty string."))
            continue
        if not isinstance(source_text, str):
            diagnostics.append(_diagnostic("sources", line, "invalid_text", "Source text must be a string.", source_id=source_id))
            continue
        if source_id in seen_source_ids:
            diagnostics.append(_diagnostic("sources", line, "duplicate_id", "Source ID is duplicated.", source_id=source_id))
            continue
        seen_source_ids.add(source_id)
        sources[source_id] = source_text

    seen_case_ids: set[str] = set()
    valid_cases = 0
    citation_count = 0
    for line, value in cases_rows:
        if not _has_exact_keys(value, _CASE_KEYS):
            diagnostics.append(_diagnostic("cases", line, "schema_error", "Case row must have exactly the required fields."))
            continue
        case_id = value["case_id"]
        unique_case_id = True
        if not isinstance(case_id, str) or not case_id.strip():
            diagnostics.append(_diagnostic("cases", line, "invalid_id", "Case ID must be a nonempty string."))
            case_id = None
        elif case_id in seen_case_ids:
            diagnostics.append(_diagnostic("cases", line, "duplicate_id", "Case ID is duplicated.", case_id=case_id))
            unique_case_id = False
        else:
            seen_case_ids.add(case_id)

        if not isinstance(value["question"], str) or not isinstance(value["answer"], str):
            diagnostics.append(_diagnostic("cases", line, "invalid_text", "Question and answer must be strings.", case_id=case_id))
        citations = value["citations"]
        if not isinstance(citations, list):
            diagnostics.append(_diagnostic("cases", line, "invalid_citations", "Citations must be an array.", case_id=case_id))
            continue
        if not citations:
            diagnostics.append(_diagnostic("cases", line, "invalid_citations", "Each case must include at least one citation.", case_id=case_id))

        case_valid = case_id is not None and unique_case_id and bool(citations)
        if not isinstance(value["question"], str) or not isinstance(value["answer"], str):
            case_valid = False
        for citation in citations:
            citation_count += 1
            if not _has_exact_keys(citation, _CITATION_KEYS):
                diagnostics.append(_diagnostic("cases", line, "citation_schema_error", "Citation must have exactly the required fields.", case_id=case_id))
                case_valid = False
                continue
            source_id, start, end, quote = (
                citation["source_id"], citation["start"], citation["end"], citation["quote"]
            )
            diagnostic_source_id = source_id if isinstance(source_id, str) else None
            if not isinstance(source_id, str) or not source_id.strip():
                diagnostics.append(_diagnostic("cases", line, "invalid_source_id", "Citation source ID must be a nonempty string.", case_id=case_id))
                case_valid = False
                continue
            if source_id not in sources:
                diagnostics.append(_diagnostic("cases", line, "unresolved_source", "Citation source ID does not resolve to a source row.", case_id=case_id, source_id=diagnostic_source_id))
                case_valid = False
                continue
            if isinstance(start, bool) or not isinstance(start, int) or isinstance(end, bool) or not isinstance(end, int):
                diagnostics.append(_diagnostic("cases", line, "invalid_span", "Citation offsets must be integers.", case_id=case_id, source_id=source_id))
                case_valid = False
                continue
            if start < 0 or end < 0 or start >= end or end > len(sources[source_id]):
                diagnostics.append(_diagnostic("cases", line, "invalid_span", "Citation span is outside the source text.", case_id=case_id, source_id=source_id))
                case_valid = False
                continue
            if not isinstance(quote, str) or quote != sources[source_id][start:end]:
                diagnostics.append(_diagnostic("cases", line, "quote_mismatch", "Citation quote does not exactly match its source span.", case_id=case_id, source_id=source_id))
                case_valid = False
        if case_valid:
            valid_cases += 1

    source_count = len(sources)
    return {
        "valid": not diagnostics,
        "source_count": source_count,
        "case_count": valid_cases,
        "citation_count": citation_count,
        "diagnostics": diagnostics,
    }
