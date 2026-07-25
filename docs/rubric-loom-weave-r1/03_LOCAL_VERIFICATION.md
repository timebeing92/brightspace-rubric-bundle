# Wave 5 — local verification

Status: green after adversarial repair

## Commands and results

```text
.venv/bin/python -m pytest --junitxml=output/tui_wave5_full_pytest.xml -q
228 tests, 0 failures, 0 errors, 1 existing skip, 31.321 seconds

.venv/bin/python scripts/vendor_from_workbench.py --check \
  --compare-ref 7c5140545548c89a254ac4502cfdd7ee6fb44255 \
  --workbench ../coursecraft_workbench
vendor pin OK: 30 files

.venv/bin/python scripts/run_synthetic_journey.py
PASS: Weave build, package validation, Unravel extraction, name round trip

git diff --check
PASS
```

The full suite includes live PTY interaction at 100 columns, the unpaced
plain/piped surface, `NO_COLOR`, `TERM=dumb`, and the existing paced Unravel
journey. It also exercises the fresh-launcher setup decline without a
pre-existing `.venv`. Both synthetic CLI/TUI runs produce byte-identical core
artifacts and producer/final receipts.

## Safety and refusal evidence

- Missing named Weave approval exits `2` after preflight and writes no
  package.
- Missing scoring and weights exit `2` with
  `SCORING_METADATA_REQUIRED` and `CRITERION_WEIGHT_REQUIRED`.
- Explicit even-spacing and equal-weight approvals appear in preflight and
  producer receipt parameters.
- A symlinked output target under `--force` is passed uncanonicalized to the
  producer; direct CLI and TUI both exit `2`, and sentinel files survive.
- A symlinked run-log path fails before launching the child and preserves its
  target.
- A stale occupied destination is not claimed as delivery.
- Modified artifact bytes, wrong receipt roles, invalid receipt state, and
  escaped paths fail closed.
- Weave-only flags without `--door weave` exit `2`; they cannot be silently
  ignored by legacy Unravel routing.
- Interrupted Weave runs exit `130` and claim no package.
- Door state remains isolated; the former flat state migrates only to
  Unravel.

## Rendered outcomes

The PTY journeys exercise source/preflight cards, label and bundle prompts,
Back edges, named approval, the real six-step board, success, interruption,
and quit. The success surface leads with `rubric_package.zip` and ends with:

> Nothing was imported. Activity attachment remains manual.
