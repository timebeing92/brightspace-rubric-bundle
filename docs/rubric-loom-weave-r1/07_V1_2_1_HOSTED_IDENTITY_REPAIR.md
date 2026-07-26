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
