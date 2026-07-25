# Wave 4 — Weave Orchestrator

Status: implemented and locally verified

## Pin

The bundle vendors 30 exact Workbench files from accepted producer commit
`7c5140545548c89a254ac4502cfdd7ee6fb44255`. The executable runtime includes
the strict producer, shared package library, extraction dependency, authoring,
extraction, and run schemas, fixtures, and upstream tests.

`scripts/vendor_from_workbench.py --check --compare-ref` verifies both the
local target bytes and the selected source inventory at that commit.

## Boundary

`scripts/run_weave_bundle.py` is process orchestration, not a second rubric
engine. It:

1. verifies the Workbench pin and source form;
2. invokes pinned producer preflight;
3. checks the producer-reported preflight envelope;
4. invokes the pinned package build;
5. runs the pinned package validator against folder and ZIP;
6. verifies the producer receipt and writes the final bundle run receipt.

It never imports the semantic producer module, opens DOCX or rubric JSON
tables, changes labels or scores, or writes D2L XML.

The final `coursecraft.run/1` wraps the pinned producer receipt because the
vendored Workbench module executes inside a downstream checkout. It records
the exact Workbench source commit, upstream run ID and receipt digest, bundle
identity, progress contract, six orchestrator steps, artifact checksums, and
the manual-only attachment boundary. The unmodified producer receipt remains
as `producer_run_receipt.json`.

## Accepted commands

Producer preflight:

```bash
.venv/bin/python scripts/run_weave_bundle.py rubric.md --preflight
```

Build with progress:

```bash
.venv/bin/python scripts/run_weave_bundle.py rubric.md \
  --output-dir output/example__weave_bundle \
  --progress-events
```

Fallback scoring and equal weights remain opt-in through
`--allow-even-spacing` and `--allow-equal-weights`. Without adequate source
evidence or explicit flags, the run exits `2` and does not create output.

## Outputs

- `rubric_package.zip` — primary rubric-only Brightspace import package
- `rubrics_d2l.xml`
- `normalized_rubric_authoring.json`
- `rubric_mapping.md`
- optional `conversion_review.md`
- `diagnostics.json`
- `producer_run_receipt.json`
- final `run_receipt.json`

`coursecraft.progress/1` advertises those paths only after they exist. Success
copy says that nothing was imported and activity attachment remains manual.

## Verification

- New orchestrator tests: 7 passed.
- Promotion, journey, and repository-control tranche: 11 passed.
- Full bundle suite after promotion: 207 tests, 206 passed and one existing
  machine-evidence-dependent skip in 21.194 seconds.
- Synthetic Weave → validate → Unravel loop: PASS.
- Direct pinned-producer and orchestrated core artifacts: byte-identical.
- Vendor target and source comparison: PASS at `7c51405`.
