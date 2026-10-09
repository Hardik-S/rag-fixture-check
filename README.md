# RAG Fixture Check

A small offline CLI for checking that IDs and exact text spans in a RAG fixture still resolve against the supplied source records. It catches broken fixture references; it does not determine whether a quote supports an answer.

## Quickstart

Requires Python 3.10 or newer. From a fresh checkout:

```console
python -m pip install .
rag-fixture-check verify examples/sources.jsonl examples/cases.jsonl --format text
```

The synthetic example should report one source, one case, and one valid citation. JSON output is available with `--format json`.

## Input contract

Source rows contain exactly `source_id` and `text`. Case rows contain exactly `case_id`, `question`, `answer`, and `citations`; each citation contains exactly `source_id`, `start`, `end`, and `quote`. Offsets are zero-based Python Unicode code-point indices and the quote must equal `text[start:end]` exactly.

The checker rejects duplicate IDs or JSON keys, malformed/non-finite JSON, invalid UTF-8, unresolved source IDs, and invalid or stale spans. Diagnostics never include source text, questions, answers, or quotes. Exit status is 0 for valid input and 2 for input/contract errors.

No model, network, retrieval, rendering, semantic-grounding judgment, or benchmark is involved. Public examples use synthetic text only.
