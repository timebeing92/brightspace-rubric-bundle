# Rubric Weave Intake Templates v1

This directory is the Workbench-owned, versioned source for two equivalent
editable Rubric Weave intake templates:

- `rubric-weave-intake-template.docx`
- `rubric-weave-intake-template.md`

Both files contain the same synthetic rubric: three editable performance
levels, three editable criterion rows, one numeric score in every level
header, and explicit positive weights totaling 100. They are presentation
assets over the accepted producer at
`71552e912b79d73a00b4d70fd97bd32386fbe2a4`; they do not add a parser or alter
`coursecraft.rubric_authoring/1`.

## Choose and edit a template

Use the DOCX when the rubric author prefers Word. Every rubric must be one
Heading 1 title followed immediately by one simple rectangular rubric table.
Rubrics without that title-and-table pairing are not read. To package more than
one rubric from the same document, repeat the complete title-and-table block for
each rubric before the instruction paragraphs. Give every rubric a unique
title.

The Word design resolves the `compact_reference_guide` preset with two named
parser-form overrides: the sole title heading has 0 pt space before it, and
there is no decorative first-page, header, or footer furniture. Those overrides
preserve the required title → table → ordinary instructions body sequence.
When a document holds multiple rubrics, the sequence becomes title → table →
title → table, repeated as needed, followed by the ordinary instructions.

Use the Markdown file when pipe-table editing is more reliable. Start every
rubric with a unique level-two heading (`## Rubric title`), followed by one
rectangular pipe table. Repeat that heading-and-table block for each additional
rubric. Escape a literal pipe inside a cell as `\|`.

In either format:

- keep one Criterion column and an optional Weight column;
- add or remove criterion rows and performance-level columns as needed;
- keep at least two uniquely named performance levels;
- keep one criterion per row;
- keep exactly one numeric score in every level header;
- keep criterion names unique and every row complete;
- do not merge or nest cells, add notes or row-number columns, or use multiple
  header rows;
- keep the included Weight column with explicit positive values totaling 100,
  or remove it only when an operator intends to review and explicitly approve
  the equal-weights fallback;
- replace all visibly synthetic title and description text before real use.

## Preflight before building

Run strict producer preflight with no fallback flags first:

```bash
.venv/bin/python scripts/make_rubric_package.py \
  --input workspace/reference/templates/rubric-weave/v1/rubric-weave-intake-template.docx \
  --preflight
```

The Markdown path works the same way. Missing or ambiguous scoring and weights
refuse. If preflight identifies such a problem, correct the source and run it
again. Use `--allow-even-spacing` or `--allow-equal-weights` only after
intentionally approving that named fallback; the producer records the approval
in diagnostics and the run receipt. No scoring source is silently invented.

## Brightspace and attachment boundary

Weave emits a rubric-only import package. A successful local build or
validation is not a Brightspace import and does not prove that Brightspace has
accepted the package. Importing the package creates rubric objects only; it
does not attach them to assignments, discussions, quizzes, or grade items.
Activity attachment is a separate manual Brightspace step.

## Deterministic source and integrity

Regenerate the two templates and `manifest.json` with:

```bash
.venv/bin/python scripts/generate_rubric_weave_intake_templates.py
```

Verify committed bytes without writing:

```bash
.venv/bin/python scripts/generate_rubric_weave_intake_templates.py --check
```

`manifest.json` records each manifest-relative asset path, version, media type,
byte count, SHA-256, and the synthetic rubric-title completion sentinel.
Downstream consumers must verify those values before listing, copying, serving,
or packaging a template. A same-session template shortcut must refuse a saved
copy whose producer preflight still reports that sentinel title. Missing or
mismatched template bytes must disable the template convenience path; they must
not change ordinary Weave producer behavior.
