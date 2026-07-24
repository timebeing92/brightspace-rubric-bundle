# Rubric Loom roadmap

Phased like the sibling bundles: each phase has deliverables and an explicit
exit condition. Nothing in a later phase starts without the earlier exit
condition or an explicit operator decision.

## R0 — Private repository activation (complete)

- Byte-pinned Workbench surface: extraction scripts, builder scripts,
  `coursecraft.rubrics/1` schema, `coursecraft.progress/1` schema, upstream
  test files and synthetic fixtures (`upstream/workbench_pin.json`).
- Bundle-only Unravel orchestrator (`scripts/run_rubric_bundle.py`) with
  contract validation and optional `coursecraft.progress/1` NDJSON.
- Synthetic journey proof with a written receipt
  (`brightspace-rubric-bundle.synthetic-journey/1`).
- Repository controls tests, CI matrix (3.11–3.13), environment bootstrap.

Exit condition: private `main` is green and no release has been cut. Met at
activation.

## R1 — Unravel hardening and release identity

- Run receipt: decide whether Unravel emits `coursecraft.run/1` (the bundle
  release receipt contract) or stays with progress events only; implement
  the decision.
- Deterministic release asset builder (`make_release_asset.py` pattern from
  the sibling bundles: clean-tree requirement, embedded source receipt,
  sidecar checksum) plus SBOM aligned to `requirements-lock.txt`.
- Version tag policy consistent with the blueprint bundle (`v1.0.0` on first
  consumable release).

Exit condition: a checksum-verified release candidate built from a clean
tree, with CI verifying release inputs.

## R2 — Weave productization

The builder door becomes a first-class product. All semantic work is
upstream-first in the Workbench; this repo re-pins after review.

- Promote the diverged staged prototype
  (`coursecraft_workbench/workspace/generated/shareable-rubric-package-builder/`)
  into the Workbench proper: source-label preservation, variable
  performance-level counts, DOCX intake (`docx_to_rubric_contract.py`), and a
  validator generalized to match — builder, validator, fixtures, and tests
  move together (the promotion requirements are recorded in the Workbench
  roadmap note of 2026-06-30). Then re-pin here.
- Round-trip adapter: `coursecraft.rubrics/1` (unraveled, verbatim) to the
  builder's authoring contract (normalized weights, thresholds). This is a
  new capability with its own fixtures and honest-diagnostics posture — the
  two shapes are deliberately different and the adapter must not guess.
- Attachment frame: rubric-to-activity association evidence and guidance
  (the manifest registers the payload but does not bind rubrics to
  activities; associations live in activity payloads — see the Workbench
  `RUBRIC_PACKAGE_BUILD_AND_LINKING_NOTES.md`). Automation here is
  explicitly a later, operator-gated decision.
- A Weave orchestrator peer to `run_rubric_bundle.py`, emitting the same
  progress contract.

Exit conditions: upstream promotion merged with its validator and fixtures;
one Brightspace field import of a woven package verified by the operator.

## R3 — Terminal Rubric Wizard (complete)

R3 was explicitly operator-authorized ahead of the still-open R1 and R2 work.
That sequencing adds a guided surface over the existing Unravel capability; it
does not imply a release candidate or a productized Weave door.

- Co-located in this repo (the quiz-bundle decision pattern: wizard
  co-located, CLI-and-events boundary). The wizard consumes the orchestrator
  CLI and `coursecraft.progress/1` only; it does not parse D2L XML or infer
  artifacts.
- Register and voice follow the operator-approved
  `docs/RUBRIC_LOOM_EXPERIENCE_FRAME.md`: workshop doctor, source and peek
  cards, commissioned options, the live step board, results and partial-
  delivery cards, plain/headless behavior, and a macOS launcher.
- The multi-tool launcher question stays governed by the ecosystem
  rule-of-three; this wizard's arrival is a data point, not a trigger
  override.

Exit condition met: the wizard drives the full Unravel journey end-to-end on
the synthetic fixture with the same artifacts as the CLI. Verified
2026-07-23 with 52 tests passing and one machine-evidence-dependent skip.

## R4 — Hosted workshop bench (trigger-gated)

- A Rubric Loom bench in `coursecraft-workshop-space`, only under the
  ecosystem bench-registry pattern and only with separate operator
  authorization (privacy gate: course exports are institutional content).
- The bench consumes a pinned release of this repo via CLI plus progress
  events; web-owned code stays presentation-only (the established web-track
  drift governance rule).

Exit condition: hosted verification of the sample journey on a pinned
release.

## Standing constraints

- Upstream-first: extraction and build semantics change in the Workbench,
  never here. The blueprint bundle's copies of the extraction scripts are
  governed by its own drift maps; this repo's copies are governed by the
  vendor pin. Both trace to the same Workbench commit lineage.
- The staged share bundle `shareable-rubric-package-builder` remains the
  colleague-facing hand-off surface until this repo reaches R2; do not
  duplicate its diverged library here in the meantime.
- License posture stays private-scaffold until the operator chooses a
  license at first public release (`LICENSE_POSTURE.md`).
