# Evaluation Rubric and Root-Cause Taxonomy

This project uses a shared evaluation rubric to assess each QA case beyond pass/fail.

## Rubric Version

- `2026-04-r1`

## Scoring Dimensions (0-5 each)

- `retrieval` (weight `0.30`)
  - Checks if retrieval is strong and expected legal references are covered.
- `grounding` (weight `0.30`)
  - Checks citation validity, quote grounding, and hallucination control.
- `policy` (weight `0.25`)
  - Checks refusal/answer mode contract and guard behavior.
- `reasoning` (weight `0.15`)
  - Checks reference usefulness and overclaim risks.

Weighted score:

```text
overall_score = sum((dimension_score / 5) * weight) * 100
```

Grades:

- `A`: >= 90
- `B`: >= 80
- `C`: >= 70
- `D`: >= 60
- `F`: < 60

## Root-Cause Taxonomy

Each failing case is mapped to one primary cause:

- `retrieval`
  - Context quality/coverage gap (missing or weak evidence retrieved).
- `prompt`
  - Instruction-following gap (answer style/citation contract not enforced strongly enough).
- `policy`
  - Orchestration/guard-state mismatch (wrong response mode, fallback behavior, clarification behavior).
- `model`
  - Generation/reasoning instability (hallucination, unsupported claims, grounding failure despite strong retrieval).

Each case also includes:

- `root_cause.confidence`
- `root_cause.evidence`
- `root_cause.scores` (internal heuristic scores for all four categories)

## Where It Appears

- `test_legal_qa.py` report (`reports/legal_qa/*.json`):
  - `summary.rubric`
  - `results[].evaluation`
- `scripts/diagnostic_sprint.py` report (`reports/diagnostics/*.json` and `.md`):
  - `summary.rubric`
  - `records[].evaluation`
  - failure causes aggregated by taxonomy
