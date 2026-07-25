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

## R1 — Unravel hardening and release identity (complete)

- Run receipt: decide whether Unravel emits `coursecraft.run/1` (the bundle
  release receipt contract) or stays with progress events only; implement
  the decision.
- Deterministic release asset builder (`make_release_asset.py` pattern from
  the sibling bundles: clean-tree requirement, embedded source receipt,
  sidecar checksum) plus SBOM aligned to `requirements-lock.txt`.
- Version tag policy consistent with the blueprint bundle (`v1.0.0` on first
  consumable release).

Exit condition met: deterministic `v1.0.0` asset and checksum published from a
clean source ref, with the manifest advertising the working Unravel surface.

## R2 — Weave productization (complete)

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

Exit conditions met 2026-07-25: strict producer accepted in Workbench,
five-package Brightspace sandbox import/re-export matrix passed with zero
semantic comparison errors, refusal created no object, the exact producer was
byte-pinned here, and the six-step Weave orchestrator passed its synthetic
round trip.

## R3 — Terminal Rubric Wizard (complete)

R3 began as the Unravel surface and now presents both accepted doors through
one shell and launcher.

- Co-located in this repo (the quiz-bundle decision pattern: wizard
  co-located, CLI-and-events boundary). Both journeys consume orchestrator
  CLIs and `coursecraft.progress/1`; Weave preflight and artifact truth come
  only from the pinned producer and final receipt.
- Register and voice follow the operator-approved
  `docs/RUBRIC_LOOM_EXPERIENCE_FRAME.md`: workshop doctor, source and peek
  cards, commissioned options, the live step board, results and partial-
  delivery cards, plain/headless behavior, and a macOS launcher.
- The multi-tool launcher question stays governed by the ecosystem
  rule-of-three; this wizard's arrival is a data point, not a trigger
  override.

Exit condition met: the wizard drives both synthetic journeys end-to-end with
CLI-equivalent artifacts, explicit fallback and write approvals, isolated
state, and unchanged Unravel regression behavior.

## R4 — Hosted workshop bench (authorized, pending pinned release)

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
- The former staged share bundle remains historical evidence. Canonical
  producer changes land in Workbench and arrive here only through the exact
  vendor pin; no downstream semantic fork is permitted.
- The repository is licensed under AGPL-3.0-or-later as chosen for the v1.0.0
  public release; `LICENSE_POSTURE.md` records that decision.
