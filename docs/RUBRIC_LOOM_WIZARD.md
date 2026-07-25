# Rubric Loom — two-door terminal wizard

`scripts/rubric_loom_wizard.py` is the single operator shell for Unravel and
Weave. `launch_rubric_loom.command` is the single macOS launcher.

```bash
.venv/bin/python scripts/rubric_loom_wizard.py
```

The shared workshop checks both orchestrators and contracts. A guided launch
then chooses a door:

- **Unravel** accepts a course export ZIP, unpacked export folder, or
  `rubrics_d2l.xml`. Its shallow export peek, DOCX/workbook/JSON options,
  progress board, partial-delivery behavior, and legacy CLI remain intact.
- **Weave** accepts supported DOCX, Markdown, and JSON authoring sources. It
  invokes producer preflight before writing, displays only producer-reported
  rubric counts, level labels, scoring sources, weight sources, and
  diagnostics, and requires the operator to type `WEAVE` before a build.

Both doors use `loom_progress.py` to consume the orchestrators'
`coursecraft.progress/1` events. Journey code supplies presentation flavor
and final result handling; the shared consumer knows no rubric semantics and
infers no artifacts.

## Non-interactive use

Every pre-R1 invocation remains Unravel:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py \
  --source path/to/export.zip --yes
```

Weave must be named and separately approved:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py \
  --door weave \
  --source path/to/rubric.md \
  --yes \
  --approve-weave \
  --output-dir output/example__weave_bundle
```

`--yes` never supplies missing rubric decisions. When the producer reports
missing scoring or weights, headless use must also name the corresponding
approval:

```bash
--allow-even-spacing
--allow-equal-weights
```

Those choices are shown before the build and recorded by the pinned producer.
Without them, preflight exits `2` and creates no output.

## Weave journey

1. Choose Weave.
2. Pick or drag a DOCX, Markdown, or JSON source.
3. Read the pinned producer preflight.
4. Review reported rubrics, labels, scoring/weight sources, and diagnostics.
5. Make only the fallback decisions the producer requests.
6. Confirm label and output folder.
7. Type the named final approval `WEAVE`.
8. Watch the orchestrator's real six-step progress board.
9. Start with the Brightspace import ZIP; review normalized JSON, mapping,
   optional DOCX review, diagnostics, and the final receipt.

The success card states: “Nothing was imported. Activity attachment remains
manual.”

Delivery claims fail closed. The card loads the final `coursecraft.run/1`
receipt and checks every named artifact's path, byte count, and SHA-256.
Incomplete, interrupted, malformed-receipt, or checksum-mismatched runs claim
no delivery.

## Interaction and terminal behavior

- `b`/`back` reverses commission prompts; the preflight is re-shown when the
  operator backs out of naming.
- `q` leaves the landing or door router without running.
- Ctrl-C returns `130`; a running child receives SIGINT and no incomplete
  Weave artifact is presented as deliverable.
- Pipes, `--plain`, `NO_COLOR`, and `TERM=dumb` contain no ANSI escapes and
  use the same words and facts as the live board.
- TTY boards are display-paced; plain, piped, and `--brisk` runs are not.
- Remembered answers use `rubric_loom.state/2`, namespaced under `unravel` and
  `weave`. R3 flat state migrates only into Unravel.
- Weave logs use randomized, exclusive files under the local `output/logs`
  lane (or `RUBRIC_LOOM_LOG_DIR`); the logger refuses symlink targets before
  launching the producer.

The launcher offers guided use, an Unravel demonstration, a Weave
demonstration, and the shared doctor. Its existing first-run environment
bootstrap remains unchanged.

## Ownership boundary

`rubric_loom_weave.py` invokes `run_weave_bundle.py` for preflight and build.
It does not import DOCX, rubric authoring, package builder, D2L XML, adapter,
or normalization modules. Repository controls enforce that boundary.

The TUI does not claim a build was imported. It does not attach rubrics to
activities. It does not replace authored labels or invent scores.
