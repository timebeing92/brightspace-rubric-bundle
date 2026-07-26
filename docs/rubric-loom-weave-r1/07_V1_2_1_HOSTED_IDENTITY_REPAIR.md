# v1.2.1 hosted release identity repair

## Finding

The first hosted Workshop Weave run used the exact v1.2.0 Markdown intake
template, passed producer preflight without a fallback, and produced a valid
rubric-only package. Its final receipt nevertheless mixed two repositories:

- `producer.repository` named `brightspace-rubric-bundle`;
- `producer.commit` contained the Workshop Space deployment commit.

The release archive was unpacked below the Workshop checkout. The bundle
orchestrator called `git rev-parse HEAD` from the archive directory without
first proving that directory was its own Git top level. Git walked to the
ambient Workshop repository and returned its commit.

The receipt was refused for promotion. The v1.2.0 release and tag remain
immutable.

## Repair

`scripts/run_weave_bundle.py` now has two explicit identity paths:

1. A source checkout may use Git only when `.git` exists at the bundle root
   and `git rev-parse --show-toplevel` resolves to that exact root.
2. A release archive reads its version, source repository, source ref, and
   source commit from its immutable `RELEASE_MANIFEST.json`.

If neither path is valid, the receipt reports unknown identity. It never
falls back to an ambient parent repository.

The release path retains the public repository label
`brightspace-rubric-bundle`, records the immutable manifest commit and ref,
and adds the normalized release repository plus manifest SHA-256 under
producer extensions.

## Verification gate

The focused runner and repository-control tests cover:

- ordinary source-checkout identity;
- a synthetic release archive nested below an unrelated Git repository;
- exact manifest source commit/ref selection instead of the ambient commit;
- honest unknown identity when the archive manifest is absent.

Before release, run the complete vendor-pin and pytest gates, build v1.2.1
twice from one immutable commit, compare the archives byte-for-byte, verify
the manifest source identity and retained template bytes, publish the archive
and checksum, and download both again for remote verification.

Downstream Workshop promotion requires a new pin and a hosted run whose final
receipt names the v1.2.1 bundle source commit. Building a package still does
not import or modify Brightspace, and rubric-to-activity attachment remains
manual.

## Published evidence

The complete repository gate passed:

- Workbench vendor pin: 36 files at `ad08b1ca1ebd…`;
- pytest: 289 passed, one expected skip;
- source commit:
  `ee61bbf4a0771c027d218b4fcb3020b974fd0d83`;
- annotated tag and release: `v1.2.1`;
- archive: `brightspace-rubric-bundle-v1.2.1.tar.gz`;
- archive bytes: 245,627;
- archive SHA-256:
  `8b739638eb6527ad9ad93c921dc70a72ee2ebcfb30bb4fe9c2ed417d23c19599`;
- matching sidecar:
  `brightspace-rubric-bundle-v1.2.1.tar.gz.sha256`;
- release:
  `https://github.com/timebeing92/brightspace-rubric-bundle/releases/tag/v1.2.1`.

Two builds using the full source SHA were byte-identical. The archive
manifest records the same full commit in both `source.ref` and
`source.commit`. The remote archive downloaded from the GitHub release was
byte-identical to the reviewed local build.

An extracted archive was then run from below the Workshop Git checkout using
the exact Markdown template. The rubric-only package completed successfully,
and its final receipt reported:

- `identity_state`: `release`;
- `producer.commit` and `producer.ref`:
  `ee61bbf4a0771c027d218b4fcb3020b974fd0d83`;
- `identity_basis`: `release_manifest`;
- template source SHA-256:
  `564ba8ebcee07281cbbe98045c8d56cc1f55e7694d7e453c49033c75db1e6830`.

The ambient Workshop commit was not used.
