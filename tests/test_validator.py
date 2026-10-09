import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from rag_fixture_check.validator import validate_files


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def valid_inputs(tmp_path: Path, text: str = "A small synthetic passage.") -> tuple[Path, Path]:
    sources = tmp_path / "sources.jsonl"
    cases = tmp_path / "cases.jsonl"
    write_jsonl(sources, [{"source_id": "src-1", "text": text}])
    quote = text[2:7]
    write_jsonl(cases, [{
        "case_id": "case-1", "question": "Synthetic question?", "answer": "Synthetic answer.",
        "citations": [{"source_id": "src-1", "start": 2, "end": 7, "quote": quote}],
    }])
    return sources, cases


def test_valid_fixture_has_deterministic_summary(tmp_path: Path) -> None:
    paths = valid_inputs(tmp_path)
    expected = {"valid": True, "source_count": 1, "case_count": 1, "citation_count": 1, "diagnostics": []}
    assert validate_files(*paths) == expected
    assert validate_files(*paths) == expected


def test_case_requires_at_least_one_citation(tmp_path: Path) -> None:
    sources, cases = valid_inputs(tmp_path)
    write_jsonl(cases, [{
        "case_id": "case-1", "question": "Synthetic question?", "answer": "Synthetic answer.", "citations": []
    }])
    result = validate_files(sources, cases)
    assert result["valid"] is False
    assert result["case_count"] == 0
    assert result["diagnostics"][0]["code"] == "invalid_citations"


def test_unicode_line_separator_inside_json_string_is_not_a_record_boundary(tmp_path: Path) -> None:
    sources = tmp_path / "sources.jsonl"
    cases = tmp_path / "cases.jsonl"
    write_jsonl(sources, [{"source_id": "src-1", "text": "A\u2028B"}])
    write_jsonl(cases, [{
        "case_id": "case-1", "question": "Synthetic?", "answer": "Synthetic.",
        "citations": [{"source_id": "src-1", "start": 1, "end": 2, "quote": "\u2028"}],
    }])
    result = validate_files(sources, cases)
    assert result["valid"] is True
    assert result["source_count"] == 1


@pytest.mark.parametrize("payload", [
    '{"source_id":"src-1","source_id":"src-2","text":"synthetic"}',
    '{"source_id":"src-1","text":"synthetic","meta":{"x":1,"x":2}}',
    '{"source_id":"src-1","text":NaN}',
    '{"source_id":"src-1","text":Infinity}',
    '{"source_id":"src-1","text":-Infinity}',
    '{"source_id":"src-1","text":"unterminated}',
])
def test_strict_json_rejections_are_private(tmp_path: Path, payload: str) -> None:
    sources, cases = valid_inputs(tmp_path)
    sources.write_text(payload + "\n", encoding="utf-8")
    result = validate_files(sources, cases)
    assert result["valid"] is False
    assert result["diagnostics"][0]["line"] == 1
    rendered = json.dumps(result)
    assert "unterminated" not in rendered
    assert "synthetic" not in rendered


def test_invalid_utf8_reports_line_without_echoing_bytes(tmp_path: Path) -> None:
    sources, cases = valid_inputs(tmp_path)
    sources.write_bytes(b'{"source_id":"ok","text":"safe"}\n\xff')
    result = validate_files(sources, cases)
    assert result["valid"] is False
    assert any(d["code"] == "invalid_utf8" and d["line"] == 2 for d in result["diagnostics"])
    assert "safe" not in json.dumps(result)


@pytest.mark.parametrize("bad_source", [
    {"source_id": "s", "text": "t", "extra": "synthetic-secret"},
    {"source_id": "s", "text": 4},
    {"source_id": "", "text": "t"},
])
def test_source_schema_and_types_are_exact(tmp_path: Path, bad_source: dict) -> None:
    sources, cases = valid_inputs(tmp_path)
    write_jsonl(sources, [bad_source])
    result = validate_files(sources, cases)
    assert result["valid"] is False
    assert result["diagnostics"]
    assert "synthetic-secret" not in json.dumps(result)


@pytest.mark.parametrize("bad_case", [
    {"case_id": "c", "question": "q", "answer": "a", "citations": [], "extra": "private"},
    {"case_id": "c", "question": 3, "answer": "a", "citations": []},
    {"case_id": "c", "question": "q", "answer": "a", "citations": "not-array"},
    {"case_id": "c", "question": "q", "answer": "a", "citations": [{"source_id": "s", "start": 0, "end": 1, "quote": "x", "extra": "private"}]},
])
def test_case_schema_and_types_are_exact(tmp_path: Path, bad_case: dict) -> None:
    sources, cases = valid_inputs(tmp_path)
    write_jsonl(sources, [{"source_id": "s", "text": "x"}])
    write_jsonl(cases, [bad_case])
    result = validate_files(sources, cases)
    assert result["valid"] is False
    assert result["case_count"] == 0
    assert "private" not in json.dumps(result)


def test_duplicate_source_and_case_ids_are_diagnosed(tmp_path: Path) -> None:
    sources, cases = valid_inputs(tmp_path)
    write_jsonl(sources, [{"source_id": "s", "text": "x"}, {"source_id": "s", "text": "y"}])
    row = {"case_id": "c", "question": "q", "answer": "a", "citations": []}
    write_jsonl(cases, [row, row])
    result = validate_files(sources, cases)
    assert [d["code"] for d in result["diagnostics"]].count("duplicate_id") == 2


def test_dangling_source_id_is_reported_without_content(tmp_path: Path) -> None:
    sources, cases = valid_inputs(tmp_path)
    write_jsonl(cases, [{"case_id": "private-case", "question": "private question", "answer": "private answer",
                        "citations": [{"source_id": "missing-source", "start": 0, "end": 1, "quote": "unique-quote-secret"}]}])
    result = validate_files(sources, cases)
    assert any(d["code"] == "unresolved_source" for d in result["diagnostics"])
    output = json.dumps(result)
    for value in ("private question", "private answer", "unique-quote-secret"):
        assert value not in output


@pytest.mark.parametrize("start,end", [(-1, 1), (0, 0), (2, 1), (0, 999), (True, 1), (0, False)])
def test_bad_span_bounds_and_types(tmp_path: Path, start, end) -> None:
    sources, cases = valid_inputs(tmp_path, "abc")
    write_jsonl(cases, [{"case_id": "c", "question": "q", "answer": "a", "citations": [
        {"source_id": "src-1", "start": start, "end": end, "quote": "a"}]}])
    result = validate_files(sources, cases)
    assert result["valid"] is False
    assert any(d["code"] == "invalid_span" for d in result["diagnostics"])


def test_exact_quote_mismatch_is_reported_without_echo(tmp_path: Path) -> None:
    sources, cases = valid_inputs(tmp_path, "alpha synthetic omega")
    write_jsonl(cases, [{"case_id": "c", "question": "q", "answer": "a", "citations": [
        {"source_id": "src-1", "start": 0, "end": 5, "quote": "secret"}]}])
    result = validate_files(sources, cases)
    assert any(d["code"] == "quote_mismatch" for d in result["diagnostics"])
    assert "secret" not in json.dumps(result)
    assert "alpha" not in json.dumps(result)


def test_unicode_offsets_are_python_code_points(tmp_path: Path) -> None:
    text = "A🙂e\u0301Z"
    sources, cases = valid_inputs(tmp_path, text)
    write_jsonl(cases, [{"case_id": "unicode", "question": "q", "answer": "a", "citations": [
        {"source_id": "src-1", "start": 1, "end": 4, "quote": "🙂e\u0301"}]}])
    assert validate_files(sources, cases)["valid"] is True


def test_diagnostics_preserve_file_line_and_input_order(tmp_path: Path) -> None:
    sources, cases = valid_inputs(tmp_path)
    sources.write_text('{"source_id":"s","text":3}\nnot-json\n', encoding="utf-8")
    cases.write_text('{"case_id":"c","question":"q","answer":"a","citations":[{"source_id":"missing","start":0,"end":1,"quote":"x"}]}\n', encoding="utf-8")
    result = validate_files(sources, cases)
    locations = [(d["file"], d["line"]) for d in result["diagnostics"]]
    assert locations == [("sources", 2), ("sources", 1), ("cases", 1)]
    assert validate_files(sources, cases)["diagnostics"] == result["diagnostics"]


@pytest.mark.parametrize(("output_format", "expected_code"), [("json", "quote_mismatch"), ("text", "quote_mismatch")])
def test_cli_exit_code_and_output_privacy(tmp_path: Path, output_format: str, expected_code: str) -> None:
    sources, cases = valid_inputs(tmp_path, "synthetic-private-source")
    write_jsonl(cases, [{"case_id": "private-case", "question": "private question", "answer": "private answer",
                        "citations": [{"source_id": "src-1", "start": 0, "end": 9, "quote": "unique-private-quote"}]}])
    proc = subprocess.run(
        [sys.executable, "-m", "rag_fixture_check", "verify", str(sources), str(cases), "--format", output_format],
        text=True, capture_output=True, check=False,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
    )
    assert proc.returncode == 2
    assert expected_code in proc.stdout
    for private_value in ("private question", "private answer", "unique-private-quote", "synthetic-private-source"):
        assert private_value not in proc.stdout
    assert proc.stderr == ""
