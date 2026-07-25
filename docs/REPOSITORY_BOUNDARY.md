# Repository boundary — brightspace-rubric-bundle

Status: activated at operator direction on 2026-07-21 (rubric-specific
bundle repo requested in-session: extraction working now, build/import and
user-facing surfaces framed). The product register — "Rubric Loom", the
Unravel / Weave doors, and the warp/weft grid metaphor — was approved by
the operator on 2026-07-21; user-facing surfaces adopt it. The register
details live in `docs/RUBRIC_LOOM_EXPERIENCE_FRAME.md`.

## Decision

GitHub repository `brightspace-rubric-bundle` is the portable producer for
the rubric product surface. The repo name follows the sibling convention;
the product name is deliberately distinct from the repo name.

## Ownership

| Repository | Owns |
| --- | --- |
| `coursecraft_workbench` | Rubric extraction and authoring contracts, extraction and build semantics, normalization and scoring rules, validator meaning, fixtures, and live-import evidence. |
| `brightspace-rubric-bundle` | The portable rubric product: byte-pinned Workbench distribution, Unravel and Weave orchestrators, progress streaming, synthetic proof, terminal Rubric Loom, release identity/assets, and installation. |
| `brightspace-blueprint-bundle` | Rubric extraction *within full blueprint runs* (the Rubric Appendix, `<label>__rubrics.*` artifacts of a blueprint bundle). Its copies of the extraction scripts stay governed by its own mirror-policy drift maps. |
| `coursecraft-workshop-space` | Presentation over one checksum-verified pinned release; it owns upload staging, process supervision, retention, browser state, accessibility, and hosted evidence, never rubric semantics. |

## Activation pin

The accepted surface is byte-pinned from `coursecraft_workbench` commit
`7c5140545548c89a254ac4502cfdd7ee6fb44255` (2026-07-25). The pin and all 30
file digests are in `upstream/workbench_pin.json`; every source is canonical,
not a generated-lane prototype. `coursecraft.progress/1` is bundle-owned and
is released separately from the Workbench pin.

## Included now

- Strict Workbench producer, extraction, adapters, builder/validator,
  `coursecraft.rubrics/1`, `coursecraft.rubric_authoring/1`, and
  `coursecraft.run/1`, with upstream tests and synthetic fixtures.
- Bundle-owned Unravel and Weave orchestrators with
  `coursecraft.progress/1`.
- One two-door terminal wizard and launcher with producer preflight, explicit
  fallback/write approvals, cancellation, and receipt-grounded outputs.
- Deterministic synthetic journey, release asset, SBOM, installation, and
  vendor mechanics.

## Explicitly excluded

- The former diverged staged builder as executable authority.
- Rubric-to-activity attachment automation.
- Production-course operation, learner data, grading, or attempts.
- Hosted upload, session, retention, and browser implementation.
- Raw course exports, real rubrics, or any institutional evidence.

## Change rule

Behavioral or contract changes start in the Workbench, pass review and tests
there, and arrive here only through
`scripts/vendor_from_workbench.py --update-pin` with an explicit reviewed
ref. Bundle-only code composes pinned behavior and never forks its meaning.
