# RAG Fixture Check

## Problem

RAG evaluation fixtures can silently become stale when source IDs change or an excerpt no longer matches the source text. This offline checker validates those references and exact spans before a fixture is used. It is a structural check, not a judgment about whether a citation supports an answer.

## Reproduce

Requires Python 3.10 or newer. From the repository root:

```console
python -m pip install .
rag-fixture-check verify examples/sources.jsonl examples/cases.jsonl --format text
```

Expected summary for the bundled synthetic fixture:

```text
Fixture check: valid
Sources: 1; cases: 1; citations: 1
```

The command exits 0 when the fixture satisfies the input contract and 2 for input or contract errors. Add `--format json` for stable machine-readable output.

## Limits and data

The checker validates JSONL shape, identifiers, source references, and exact zero-based Python Unicode code-point spans. It does not run retrieval, call a model or network service, or assess semantic grounding, factuality, relevance, answer quality, or benchmark performance. Diagnostics do not include fixture text. Bundled public examples are synthetic and contain no real user or customer data.
