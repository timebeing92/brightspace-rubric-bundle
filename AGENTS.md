# Repository instructions

## Authority boundary

`coursecraft_workbench` owns rubric schemas, extraction and build semantics,
normalization rules, and live-import evidence. Files listed in
`upstream/workbench_pin.json` are mechanically promoted from one immutable
Workbench commit. Do not edit those targets here. Change upstream behavior in
the Workbench first, verify it there, then run
`scripts/vendor_from_workbench.py --update-pin` with an explicit reviewed
ref.

The rubric extraction scripts also exist inside
`brightspace-blueprint-bundle` under that repo's mirror-policy drift maps. A
fix that touches them lands in the Workbench once and flows to both
downstream copies; never patch one copy in place.

Bundle-only files (the Unravel orchestrator, synthetic journey, environment
and release mechanics, experience docs, and the later terminal wizard) may be
authored here. They compose pinned behavior; they must not re-parse D2L XML
beyond presence detection or fork upstream semantics.

## Privacy and evidence

Never commit raw course exports, real course rubrics, student data, tenant
identifiers, cookies, or tokens. Tests and examples must be synthetic or
sanitized; the pinned fixtures (`tiny_rubrics_export`, `rubric_package`) are
the model. Generated artifacts stay in the gitignored `input/` and `output/`
lanes.

## Verification

Before committing, run:

```bash
.venv/bin/python scripts/vendor_from_workbench.py --check
.venv/bin/python -m pytest
```

The synthetic journey (`scripts/run_synthetic_journey.py`) is exercised by
the test suite; run it directly when you need a receipt to cite.

Do not cut a release, publish an asset, or run a live Brightspace import
without explicit operator authorization.
