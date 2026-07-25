# brightspace-rubric-bundle

This repository is the portable producer for **Rubric Loom**: one rubric
service with two doors that converge on the Brightspace rubric dialect
(`rubrics_d2l.xml`, schemaversion v2011).

- **Unravel**: a Brightspace course export, an unpacked export
  folder, or a bare `rubrics_d2l.xml` becomes a review workbook, a
  `coursecraft.rubrics/1` JSON document validated against the vendored
  schema, and a reviewer DOCX. One command:

  ```bash
  .venv/bin/python scripts/run_rubric_bundle.py path/to/export.zip
  ```

  Attribute values and authored wording are preserved verbatim; nothing is
  inferred. Add `--progress-events` to stream `coursecraft.progress/1`
  NDJSON for wizard-style consumers.

- **Weave**: the pinned Workbench producer accepts supported DOCX rubric
  tables, Markdown tables, `coursecraft.rubric_authoring/1` JSON, eligible
  `coursecraft.rubrics/1`, and the documented legacy JSON shape. The strict
  bundle orchestrator preflights, builds, validates, and receipts a
  rubric-only import package:

  ```bash
  .venv/bin/python scripts/run_weave_bundle.py rubric.md --preflight
  .venv/bin/python scripts/run_weave_bundle.py rubric.md \
    --output-dir output/example__weave_bundle
  ```

  Missing scoring or weights refuse unless their explicit approval flags are
  supplied. Nothing is imported, and activity attachment remains manual.

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

## The terminal wizard (two doors)

```bash
.venv/bin/python scripts/rubric_loom_wizard.py
```

Or double-click `launch_rubric_loom.command` (macOS): one launcher offers the
guided two-door Loom, demonstrations for both doors, and the workshop doctor.
On a fresh machine it offers to build the `.venv` first.

Unravel retains its export peek and review artifacts. Weave invokes producer
preflight, shows only producer-reported labels and scoring evidence, requires
a named final approval, and leads with the receipt-grounded import ZIP.
Both doors share the doctor, terminal kit, progress-event consumer,
cancellation behavior, plain mode, launcher, and door-isolated remembered
state. Legacy `--source PATH --yes` remains Unravel. Headless Weave requires
`--door weave --source PATH --yes --approve-weave`. See
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

## Build a release asset

```bash
.venv/bin/python scripts/make_release_asset.py --ref <tag-or-commit>
```

The builder exports one explicit ref (clean tree required; `--allow-dirty`
builds the named ref anyway), stages `RELEASE_MANIFEST.json`
(`coursecraft.bundle_release/1`: version, source receipt, contract and
runtime digests, and the Unravel capability record), writes a reproducible
`dist/brightspace-rubric-bundle-v<VERSION>.tar.gz`, and drops a matching
`.sha256` sidecar. The version is read from `VERSION` at that ref, and the
build refuses to advertise Unravel if the orchestrator has lost its runtime
markers. Cutting, tagging, and publishing a release stay operator decisions.

## Current surface

| Piece | Status |
| --- | --- |
| `scripts/run_rubric_bundle.py` (Unravel orchestrator) | Working; emits `coursecraft.progress/1` on request |
| `scripts/make_release_asset.py` (release machinery) | Working; deterministic asset, sidecar, and manifest — no release cut yet |
| Pinned extraction scripts + `coursecraft.rubrics/1` schema | Byte-identical to Workbench at the pin commit |
| `scripts/run_weave_bundle.py` (Weave orchestrator) | Working; strict preflight, six progress steps, validated outputs, final receipt |
| `scripts/run_synthetic_journey.py` | Working proof with a written receipt |
| Terminal Rubric Wizard | Working two-door surface; producer preflight, named Weave approval, shared progress board, receipt-grounded results, plain/headless mode, one macOS launcher |
| Hosted workshop bench | Authorized next consumer; see `ROADMAP.md` R4 |

The ownership decision record is `docs/REPOSITORY_BOUNDARY.md`. The phased
plan is `ROADMAP.md`. Agent rules are `AGENTS.md`.
