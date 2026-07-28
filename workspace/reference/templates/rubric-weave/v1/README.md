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

Use the DOCX when the rubric author prefers Word. Keep the accepted Word shape:
exactly one title heading immediately before one simple rectangular rubric
table, followed by the short ordinary-paragraph instructions. Do not add
another paragraph before the table, merge cells, nest tables, add auxiliary
columns, use multiple header bands, or detach scoring into another table.

The Word design resolves the `compact_reference_guide` preset with two named
parser-form overrides: the sole title heading has 0 pt space before it, and
there is no decorative first-page, header, or footer furniture. Those overrides
preserve the required title → table → ordinary instructions body sequence.

Use the Markdown file when pipe-table editing is more reliable. Keep one
level-two rubric heading, one rectangular pipe table, one Criterion column, at
least two uniquely named level columns, and complete description cells. Escape
a literal pipe inside a cell as `\|`.

In either format:

- add or remove criterion rows and performance-level columns as needed;
- keep at least two uniquely named performance levels;
- keep one criterion per row;
- keep exactly one numeric score in every level header;
- keep criterion names unique and every row complete;
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
byte count, and SHA-256. Downstream consumers must verify those values before
listing, copying, serving, or packaging a template. Missing or mismatched
template bytes must disable the template convenience path; they must not change
ordinary Weave producer behavior.
