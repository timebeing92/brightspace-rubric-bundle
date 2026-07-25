# Wave 0 — Promotion and pin baseline

## Assignment boundary

- **Only permitted write:** `docs/rubric-loom-weave-r1/00_PROMOTION_AND_PIN.md`
- **Required baseline checks (before any production change):**
  - `.venv/bin/python scripts/vendor_from_workbench.py --check`
  - `.venv/bin/python -m pytest`
  - `.venv/bin/python scripts/run_synthetic_journey.py`

This record is a bounded, read-only baseline inventory for the Rubric Loom
Weave R1 commission. No source, fixture, test, release, remote, or Brightspace
state was modified by this evidence pass.

## Compact index

| Area | Current evidence | Disposition |
| --- | --- | --- |
| Repository | `main` at `837cd1449818290658f36ebeb83be5799079e89e`; local tracking ref `origin/main` is the same commit (`0` ahead / `0` behind). | No fetch was performed, so this is local tracking alignment, not a freshness claim about the remote. |
| Local change protection | Before this record, the tracked worktree was clean. After the required checks, the only non-ignored path is this assigned documentation directory; generated `.pytest_cache/`, `output/`, and bytecode lanes are ignored. | No unrelated user change was found or modified. |
| Workbench vendor pin | `coursecraft.workbench_vendor_pin/1`, `coursecraft-workbench` `main@5f1b78b3da8d1e5701ffff4e302b8503b6cd17f6`, committed `2026-07-20T22:19:07-04:00`, 21 pinned files. | Mechanical check passed; semantic changes remain upstream-first. |
| Release identity | Annotated `v1.0.0` tag object `b685a587bcd80c654ff68c694b37154d3440d698` dereferences to `e146c49c673927355cb03e3b2818a9f7e597c68d`; subject: `Rubric Loom Bundle v1.0.0 — first consumable Unravel release`. Current `HEAD` is one commit after it (`v1.0.0-1-g837cd14`). | The locally present v1.0.0 asset and its sidecar verify to the commission’s SHA-256. |
| Release manifest/capabilities | The local asset embeds `coursecraft.bundle_release/1`, source ref `v1.0.0`, source commit `e146c49…`, and only an enabled `unravel` capability. | Release machinery has no `weave` capability record yet; this is the intended Wave 0 baseline. |
| Two doors now | The pinned builder and synthetic journey establish a fixture-level Weave → validate → Unravel name-survival loop. The product orchestrator/wizard/release manifest expose only Unravel. | Do not infer a productized Weave door from the synthetic journey. |
| Documentation reconciliation | Several current docs still say no release has been cut, R1 is not complete, or hosted/R4 remains trigger-gated. | These are Wave 0 update candidates; no existing documentation was edited by this pass. |

## Repository, remote, and release evidence

- Branch/tracking at inspection: `main...origin/main`; both point to
  `837cd1449818290658f36ebeb83be5799079e89e` (`Adopt the family license
  pairing: AGPL-3.0-or-later with commercial terms`).
- Origin fetch/push URL:
  `https://github.com/timebeing92/brightspace-rubric-bundle.git`.
- Local comparison `HEAD...origin/main`: `0` ahead, `0` behind. Per the
  assignment boundary, no fetch or other remote mutation occurred.
- `v1.0.0` is an annotated tag made `2026-07-25T00:31:37-04:00`; it targets
  commit `e146c49c673927355cb03e3b2818a9f7e597c68d` (`2026-07-25T00:31:36-04:00`,
  `Add release asset machinery; set version 1.0.0`).
- Local release asset:
  `dist/brightspace-rubric-bundle-v1.0.0.tar.gz`; SHA-256
  `7094c177d248cfc4f75f9edf84c34b134bcfbf5f02536e558d908b42eb056fe2`.
  Its `.sha256` sidecar matches exactly.
- A read-only GitHub release lookup could not reach `api.github.com`; no
  remote release/asset metadata is asserted beyond the local tag, archive,
  sidecar, and embedded manifest.

## Vendor pin and exact digests

`scripts/vendor_from_workbench.py --check` verifies the following
`coursecraft.workbench_vendor_pin/1` inventory as byte-identical to
`main@5f1b78b3da8d1e5701ffff4e302b8503b6cd17f6`:

| Source → target | SHA-256 |
| --- | --- |
| `scripts/build_rubric_package.py` → same | `12e44333c479e30765dbdf2539505d8202f4d0f2dd1e5f0b5b471584d7185177` |
| `scripts/common_xml.py` → same | `27e8e32971887eded7f4e1d54eb91a49e96eaebd0f51b942908feab6a9903430` |
| `scripts/extract_course_context.py` → same | `5e9ac57f3ffca79fc75e4af12cc616094c6f241582078604260454077e1e2022` |
| `scripts/extract_rubrics_to_workbook.py` → same | `596e783c8538f50ecdebf7a76a798f12501d199e497584693e83a79dc36a1e3e` |
| `scripts/flat_markdown_to_json.py` → same | `d901b7dd2cd85fcaf57243b89bfb8497872f575dc658813e3c9ed355f6ae180e` |
| `scripts/rubric_package_lib.py` → same | `6c4198fb55ca5f023fd2a8eb1959aa2feaa3422e8f93b9a40b5b606ae1a723c8` |
| `scripts/rubrics_to_docx.py` → same | `f1c15a635f3cd13e845e109754b57df155b174611d40cfa0beb92e4b4977b111` |
| `scripts/validate_rubric_package.py` → same | `68f34a721d48a555087050ccb0355f6b0c70b836a79fa6f99c1f62c3b319a458` |
| `tests/fixtures/rubric_package/context/reference_course_shell/README.md` → same | `c90f04a0b28a224cd9889ae874c0b8a8608694f9c812f29eb6e3cb3aa29e0a5b` |
| `tests/fixtures/rubric_package/context/reference_course_shell/imsmanifest.xml` → same | `27b07f17ac72237b1af6866f47995235196d00592de172add7d2cfd550f25d39` |
| `tests/fixtures/rubric_package/context/reference_course_shell/orgunitconfig/orgunitconfig.xml` → same | `a1cdaaf0196b937990f86d40f34872d6da0b2b35b529fe4ec75ae121c2808887` |
| `tests/fixtures/rubric_package/input/rubrics.example.json` → same | `624b2fcb8a44bdc11805310b1b3581b3c93d40730e142f49c7e801d4788ebd32` |
| `tests/fixtures/rubric_package/input/rubrics_flat.example.md` → same | `61b389a0574b407e1df09ffe9803b6c6becd973685409cf2ed5109fc7c07cece` |
| `tests/fixtures/rubric_package/input/rubrics_flat_custom_overall_thresholds.example.md` → same | `ca34afba55717ff99d842ba2cf16796b69d90934dec3485f6b641a939241cf4f` |
| `tests/fixtures/rubric_package/input/rubrics_flat_flexible_columns.example.md` → same | `0f880bfdb9f2b832bef453283e6c96e44c535b30e1ca0f3b207bc28a35d7d84c` |
| `tests/fixtures/rubric_package/input/rubrics_flat_inferred_levels.example.md` → same | `9a3cf71f17191f950dec843ed0138708eb571110dff561b53e349537ffabbe4f` |
| `tests/fixtures/tiny_rubrics_export/rubrics_d2l.xml` → same | `92a28e41d6f3a925c65117870210187aeb56c094059c18de3dfa4766dddbfe87` |
| `tests/test_extract_rubrics_to_workbook.py` → same | `4071c3c6805a2d65dceb1fbcaab555f643d70de8f0893412691fe9ce29d045df` |
| `tests/test_rubric_package_builder.py` → same | `ae570f1f43466c56cfa115d643b08e8337e3e29071831b0f355550d855160c6b` |
| `workspace/generated/shareable-brightspace-blueprint-bundle/schemas/progress_events_schema.json` → `workspace/reference/schemas/progress/progress_events_schema.json` | `7588cf71eecebcadfe56f07ceb3eb77b748ba6fd601765ec2f3658a2a5dca5c0` |
| `workspace/reference/schemas/rubrics/rubrics_schema.json` → same | `8997f8546d803070ec6d38235a25563d3b63a71210b09fb444ed5690ecf3a0b6` |

## Capability and machinery baseline

The release builder creates a deterministic, normalized tarball and embeds
`RELEASE_MANIFEST.json` with contract and runtime receipts. Its marker gate
requires these Unravel facts before advertising a capability:

- entry point: `scripts/run_rubric_bundle.py`;
- accepted source forms: course export ZIP, unpacked export folder, or bare
  `rubrics_d2l.xml`;
- events: `coursecraft.progress/1` behind `--progress-events`;
- output contract: `coursecraft.rubrics/1` and `__rubrics.xlsx`,
  `__rubrics.json`, `__rubrics.docx` artifacts;
- ordered steps: Locate rubric evidence; Extract rubric grids; Validate rubric
  contract; Render rubric review DOCX;
- exits: `0` success, `1` step failure, `2` usage/environment, `3` no rubric
  evidence.

The v1.0.0 asset manifest’s contract digests are
`coursecraft.rubrics/1` `8997f8546d803070ec6d38235a25563d3b63a71210b09fb444ed5690ecf3a0b6`
and `coursecraft.progress/1` `7588cf71eecebcadfe56f07ceb3eb77b748ba6fd601765ec2f3658a2a5dca5c0`.
It lists exactly the same four Unravel runtime files; the orchestrator hash is
`10b5a74a9bf95a38000f784e35ec25c52e68fc639dbc2cdc3e801bcd05f0875d`.
There is no Weave entry point, marker gate, or capability record in the
release machinery or v1.0.0 manifest.

The terminal wizard is likewise Unravel-only: it launches the existing
orchestrator and consumes its real progress events; its documentation says
Weave is absent rather than disabled. `run_synthetic_journey.py` is a useful
fixture proof, not a portable Weave orchestration surface: it directly calls
the pinned builder and validator, then verifies that two synthetic rubric
names survive Weave → Unravel.

## Reconciliation candidates (not edited here)

- `ROADMAP.md`: R0’s completed exit says “no release has been cut”; R1’s
  v1.0.0/release-asset exit is not marked complete despite the local v1.0.0
  tag, asset, sidecar, and manifest. R4 still says trigger-gated.
- `README.md`: describes Weave as frame-stage/not productized (still accurate
  for the public product surface), but says release machinery has “no release
  cut yet” and the hosted bench is trigger-gated. Those latter claims conflict
  with local v1.0.0 evidence and the activated commission’s stated R4-Unravel
  completion, respectively.
- `docs/REPOSITORY_BOUNDARY.md`: calls the terminal wizard “future” although
  R3 is completed, and calls the hosted bench conditional/R4-gated.
- `docs/RUBRIC_LOOM_EXPERIENCE_FRAME.md`: describes R3 and R4 as future gates;
  R3 is already complete. Its Weave R2 framing remains an accurate current
  product-boundary statement.
- `docs/RUBRIC_LOOM_WIZARD.md`: “Weave is absent, not disabled” accurately
  describes the current implementation; it becomes a deliberate Wave 2
  incorporation target, not a baseline typo.

## Required local verification

| Command | Result |
| --- | --- |
| `.venv/bin/python scripts/vendor_from_workbench.py --check` | PASS — `vendor pin OK: 21 files at 5f1b78b3da8d` |
| `.venv/bin/python -m pytest` | PASS — `64 passed, 1 skipped in 16.22s` |
| `.venv/bin/python scripts/run_synthetic_journey.py` | PASS — four steps: weave build, weave validation, Unravel extraction/validation/DOCX, and rubric-name loop check; receipt `output/synthetic_journey/journey_receipt.json` (`completed_at` `2026-07-25T16:17:59+00:00`). |

The journey receipt reports two surviving synthetic rubric names:
`Project Checkpoint 1: Organization Selection and AI Risk Analysis` and
`Week 1 Discussion: Introductions and Predictions`.

## Scope and preservation result

No code, fixture, test, pin, manifest, tag, release asset, remote, or
Brightspace state was modified. The only non-ignored worktree change created
by this assignment is this file. The direct journey command populated its
documented, ignored `output/synthetic_journey/` lane.
