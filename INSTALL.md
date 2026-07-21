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

## Verify before committing

```bash
.venv/bin/python scripts/vendor_from_workbench.py --check
.venv/bin/python -m pytest
```
