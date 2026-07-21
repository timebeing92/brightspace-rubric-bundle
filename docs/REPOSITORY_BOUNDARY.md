# Repository boundary — brightspace-rubric-bundle

Status: activated at operator direction on 2026-07-21 (rubric-specific
bundle repo requested in-session: extraction working now, build/import and
user-facing surfaces framed). The product register name "Rubric Loom" and
its door vocabulary (Unravel / Weave) are a proposal recorded in
`docs/RUBRIC_LOOM_EXPERIENCE_FRAME.md` and await operator confirmation
before any user-facing surface adopts them.

## Decision

GitHub repository `brightspace-rubric-bundle` is the portable producer for
the rubric product surface. The repo name follows the sibling convention;
the product name is deliberately distinct from the repo name.

## Ownership

| Repository | Owns |
| --- | --- |
| `coursecraft_workbench` | Rubric contracts (`coursecraft.rubrics/1`), extraction and build semantics, normalization rules, validator meaning, live-import evidence, and the staged colleague hand-off bundle. |
| `brightspace-rubric-bundle` | The portable rubric producer: pinned downstream distribution, the Unravel orchestrator, synthetic proof and receipts, release identity and assets, installation, and the future terminal Rubric Wizard. |
| `brightspace-blueprint-bundle` | Rubric extraction *within full blueprint runs* (the Rubric Appendix, `<label>__rubrics.*` artifacts of a blueprint bundle). Its copies of the extraction scripts stay governed by its own mirror-policy drift maps. |
| `coursecraft-workshop-space` | A hosted Rubric Loom bench only if separately authorized (ROADMAP R4). |

## Activation pin

The activation surface is byte-pinned from `coursecraft_workbench` commit
`5f1b78b3da8d1e5701ffff4e302b8503b6cd17f6` (2026-07-20). The pin and every
file digest are in `upstream/workbench_pin.json`. One pinned source lives in
the Workbench's generated lane by design: the `coursecraft.progress/1`
schema is authored bundle-side in the blueprint bundle, and the Workbench's
retained staged copy is the pin source; ecosystem contract checks keep all
copies byte-identical.

## Included now

- Extraction scripts (`extract_rubrics_to_workbook.py`, `rubrics_to_docx.py`,
  `common_xml.py`) and the `coursecraft.rubrics/1` schema.
- Builder scripts (`build_rubric_package.py`, `validate_rubric_package.py`,
  `rubric_package_lib.py`, `flat_markdown_to_json.py`,
  `extract_course_context.py`) — functional, frame stage.
- Upstream rubric test files and their synthetic fixtures.
- Bundle-only orchestration, journey, environment, and vendor mechanics.

## Explicitly excluded

- The diverged staged builder prototype (label preservation, variable level
  counts, DOCX intake) — promotion is upstream-first at R2.
- Any XLSX/JSON round-trip adapter (new capability, R2).
- Rubric-to-activity attachment automation (operator-gated, R2 frame only).
- The terminal wizard build (R3) and any hosted bench (R4).
- Release cutting, public visibility, and license selection.
- Raw course exports, real rubrics, or any institutional evidence.

## Change rule

Behavioral or contract changes start in the Workbench, pass review and tests
there, and arrive here only through
`scripts/vendor_from_workbench.py --update-pin` with an explicit reviewed
ref. Bundle-only code composes pinned behavior and never forks its meaning.
