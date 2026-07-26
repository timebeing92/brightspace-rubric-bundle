# Install and run

## Requirements

Python 3.11, 3.12, or 3.13 (not 3.14; not Anaconda). macOS, Linux, and
Windows are all expected to work; CI covers 3.11–3.13 on Linux.

## Setup

```bash
python3.13 scripts/bootstrap_env.py --dev
```

This creates `.venv/` and installs the runtime and test dependencies. Use
`--locked` to install the exact pinned versions from
`requirements-lock.txt`.

## Unravel a course export

```bash
.venv/bin/python scripts/run_rubric_bundle.py "path/to/Course Export.zip"
```

The source may be an export zip, an unpacked export folder, or a bare
`rubrics_d2l.xml`. Outputs land in `output/<label>__rubric_bundle/`:

- `<label>__rubrics.xlsx` — review workbook (criteria × levels grids plus an
  Overall Levels sheet)
- `<label>__rubrics.json` — `coursecraft.rubrics/1` document, validated
  against the vendored schema before the run reports success
- `<label>__rubrics.docx` — reviewer document (skip with `--no-docx`)

Useful flags: `--label` to control the output stem, `--output-dir` to choose
the destination, `--progress-events` to stream `coursecraft.progress/1`
NDJSON, `--step-timeout` for slow machines.

Exit codes: `0` success, `1` step failure, `2` usage or environment error,
`3` the source contains no rubric evidence.

## Prove the loop on synthetic fixtures

```bash
.venv/bin/python scripts/run_synthetic_journey.py
```

## Start Weave from a pinned template

List the exact Word and Markdown assets without writing:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py \
  --door weave --list-templates --plain
```

Copy one only to an explicit file destination:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py \
  --door weave \
  --copy-template rubric-weave-intake-template.docx \
  --template-destination "path/to/my-rubric.docx" \
  --plain
```

Use `--replace-template` only as a separate, intentional replacement of an
existing regular file. Symlink and non-regular destinations are refused.
Complete and save the editable copy, then return to the wizard and select it.
Producer preflight comes before the named `WEAVE` write approval. Correct
missing scoring evidence or explicitly approve only the fallback the producer
permits; no score or weight is silently invented.

Downloading or completing the template makes no Brightspace change. Building
the validated rubric-only package is not an import. Import and manual
attachment to an assignment, discussion, quiz, or grade item happen later in
Brightspace.

## Verify before committing

```bash
.venv/bin/python scripts/vendor_from_workbench.py --check
.venv/bin/python -m pytest
```
