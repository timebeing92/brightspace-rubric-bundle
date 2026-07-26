# Wave 6 — release evidence

Status: v1.1.0 release candidate approved; publication pending

Historical note: this file records the v1.1.0 gate and is intentionally not
rewritten as v1.2.0 evidence. The immutable v1.1.0 release lacks intake
templates. The additive template/source-binding candidate is recorded in
`06_V1_2_0_TEMPLATE_RELEASE_CANDIDATE.md`.

## Compatibility decision

Weave is additive:

- the Unravel CLI entry point, source forms, four progress steps, artifacts,
  exit codes, and legacy terminal routing are unchanged;
- the new Weave CLI and terminal door require explicit selection;
- the existing v1.0.0 Workshop fetch contract accepts the additive manifest
  fields.

The correct version is therefore `1.1.0`.

## Release contract

`RELEASE_MANIFEST.json` advertises `unravel` and `weave` independently.
Weave records:

- strict orchestrator and terminal entry points;
- DOCX, Markdown, authoring JSON, eligible extraction JSON, and legacy JSON
  source forms;
- fixed/optional output artifacts and producer roles;
- `coursecraft.rubric_authoring/1`, eligible `coursecraft.rubrics/1`,
  `coursecraft.progress/1`, and `coursecraft.run/1`;
- exact six progress steps and exit codes;
- explicit fallback and terminal approval flags;
- exact Workbench producer pin;
- `manual_only` activity attachment.

The build refuses when either door loses its own required runtime markers.

## SBOM and determinism

`SBOM.json` uses `coursecraft.bundle_sbom/1` and is generated
deterministically from `requirements-lock.txt`. It records the lock digest,
component count, exact names/versions, and PyPI package URLs. The manifest
receipts the SBOM path and digest.

The archive normalizes ordering, ownership, names, and timestamps; gzip mtime
is zero. Two builds from the same final ref must be byte-identical.

## Candidate verification

- Independent adversarial release review: PASS, with no unresolved findings.
- Full test suite: 233 tests, 0 failures, 0 errors, 1 skip.
- Exact Workbench vendor check: PASS for all 30 files at
  `7c5140545548c89a254ac4502cfdd7ee6fb44255`.
- Synthetic Weave → Unravel round trip: PASS.
- `git diff --check`: PASS.

## Publication evidence

The immutable tag, source commit, asset name, byte count, SHA-256, public
release URL, and public re-download verification will be filled in the
post-publication source follow-up. This candidate document deliberately does
not predict those values.
