# The synthetic journey

`scripts/run_synthetic_journey.py` proves both Rubric Loom doors against
each other on purely synthetic fixture content, and writes a receipt.

## What it does

1. **Weave** — builds a rubric-only D2L import package from the pinned flat
   markdown fixture
   (`tests/fixtures/rubric_package/input/rubrics_flat.example.md`) with the
   pinned reference course shell as context, using the pinned Workbench
   builder.
2. **Validate** — runs the pinned package validator; the package must report
   `VALID`.
3. **Unravel** — points `run_rubric_bundle.py` at the woven package
   directory; extraction, `coursecraft.rubrics/1` validation, and the DOCX
   render must all succeed.
4. **Loop check** — the rubric names in the builder's normalized contract
   must exactly match the names in the unraveled document.

Because the builder writes exactly the dialect the extractor reads
(`rubrics_d2l.xml`, schemaversion v2011), a green journey demonstrates the
two doors converge — the structural claim this repository exists to keep
true.

## Running it

```bash
.venv/bin/python scripts/run_synthetic_journey.py
# or into a chosen folder:
.venv/bin/python scripts/run_synthetic_journey.py --output-dir output/journey_2026-07-21
```

## The receipt

`journey_receipt.json` (schema
`brightspace-rubric-bundle.synthetic-journey/1`) records status, UTC
completion time, each step with its outcome, the surviving rubric names, and
the artifact paths. A failed journey still writes a receipt with the failing
step and message.

The test suite runs the journey into a temporary directory on every
`pytest` invocation, so CI keeps the loop honest.
