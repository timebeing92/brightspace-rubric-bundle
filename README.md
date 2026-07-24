# brightspace-rubric-bundle

This repository is the portable producer for **Rubric Loom**: one rubric
service with two doors that converge on the Brightspace rubric dialect
(`rubrics_d2l.xml`, schemaversion v2011).

- **Unravel** (working now): a Brightspace course export, an unpacked export
  folder, or a bare `rubrics_d2l.xml` becomes a review workbook, a
  `coursecraft.rubrics/1` JSON document validated against the vendored
  schema, and a reviewer DOCX. One command:

  ```bash
  .venv/bin/python scripts/run_rubric_bundle.py path/to/export.zip
  ```

  Attribute values and authored wording are preserved verbatim; nothing is
  inferred. Add `--progress-events` to stream `coursecraft.progress/1`
  NDJSON for wizard-style consumers.

- **Weave** (present, frame stage): the pinned Workbench builder turns a flat
  markdown or JSON rubric contract into a rubric-only D2L import package and
  validates it (`scripts/build_rubric_package.py`,
  `scripts/validate_rubric_package.py`). The builder is live-import verified
  upstream, but this repo has not yet productized the door — no orchestrator,
  no DOCX intake, no round trip from unraveled output. See `ROADMAP.md` R2
  before extending it.

## Ownership

`coursecraft_workbench` remains the upstream owner of rubric contracts,
extraction and build semantics, and live-import evidence. This repo contains
byte-pinned downstream copies of the portable producer files; the pin and
every promoted file digest are recorded in `upstream/workbench_pin.json`.
The rubric extraction scripts also ship inside `brightspace-blueprint-bundle`
as part of full blueprint runs; both downstream copies trace to the same
Workbench source, and fixes land upstream first.

Bundle-only code (the orchestrator, the synthetic journey, release and
environment mechanics, and the later terminal Rubric Wizard) may be authored
here. It must not silently fork upstream semantics.

## Install and run the synthetic proof

```bash
python3.13 scripts/bootstrap_env.py --dev
.venv/bin/python scripts/run_synthetic_journey.py
```

The journey weaves an import package from a synthetic fixture contract,
validates it, unravels it back through extraction, and asserts the rubric
names survive the loop. The receipt lands in
`output/synthetic_journey/journey_receipt.json`. See
`docs/SYNTHETIC_JOURNEY.md`.

## The terminal wizard (Unravel, guided)

```bash
.venv/bin/python scripts/rubric_loom_wizard.py
```

Or double-click `launch_rubric_loom.command` (macOS): it offers the
guided loom, a demonstration unravel on the synthetic fixture, and the
workshop doctor — and on a fresh machine it offers to build the `.venv`
first via `scripts/bootstrap_env.py`.

The Rubric Loom wizard (roadmap R3) walks the Unravel door in the family
register: doctor checklist, source pick and peek card, commissioned
options, a live step board over the orchestrator's real
`coursecraft.progress/1` events, and a results card whose reviewer DOCX
is marked "start here". Piped and `--plain` runs stay escape-free;
`--source PATH --yes` runs it non-interactively. See
`docs/RUBRIC_LOOM_WIZARD.md`.

## Verify the source boundary

```bash
.venv/bin/python scripts/vendor_from_workbench.py --check
.venv/bin/python scripts/vendor_from_workbench.py --compare-ref main --workbench ../coursecraft_workbench
```

Promotion happens only after the named Workbench ref has passed its upstream
review and tests:

```bash
.venv/bin/python scripts/vendor_from_workbench.py --update-pin --workbench ../coursecraft_workbench --ref <reviewed-commit>
```

## Current surface

| Piece | Status |
| --- | --- |
| `scripts/run_rubric_bundle.py` (Unravel orchestrator) | Working; emits `coursecraft.progress/1` on request |
| Pinned extraction scripts + `coursecraft.rubrics/1` schema | Byte-identical to Workbench at the pin commit |
| Pinned builder scripts (Weave) | Functional CLIs; door not yet productized |
| `scripts/run_synthetic_journey.py` | Working proof with a written receipt |
| Terminal Rubric Wizard | Working Unravel surface; guided source selection, doctor, progress board, results card, plain/headless mode, and macOS launcher |
| Hosted workshop bench | Trigger-gated; see `ROADMAP.md` R4 |

The ownership decision record is `docs/REPOSITORY_BOUNDARY.md`. The phased
plan is `ROADMAP.md`. Agent rules are `AGENTS.md`.
