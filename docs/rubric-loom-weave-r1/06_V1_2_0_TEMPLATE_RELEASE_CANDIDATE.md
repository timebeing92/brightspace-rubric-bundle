# v1.2.0 template release evidence

Status: published and remotely verified; the earlier local archive remains
superseded and is not release evidence

## Additive promotion

The bundle mechanically vendors 36 exact files from immutable Workbench ref
`ad08b1ca1ebd0889bba3353cd87ca71b88f26514`. The new surface is the
Workbench-owned deterministic template generator, its upstream test, the
`rubric-weave/v1` README and manifest, and the exact Word and Markdown assets.
The pin separately retains accepted producer semantics at
`7c5140545548c89a254ac4502cfdd7ee6fb44255`; selected non-template producer,
schema, fixture, and test bytes are unchanged between those refs.

Template asset identities:

| Name | Version | Media type | Bytes | SHA-256 |
| --- | --- | --- | ---: | --- |
| `rubric-weave-intake-template.docx` | `v1` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | 36,204 | `349a2c3d1f68b01476bc271be7e1e3f7c303edbc98739eac3d1eee8aafce104c` |
| `rubric-weave-intake-template.md` | `v1` | `text/markdown` | 2,410 | `564ba8ebcee07281cbbe98045c8d56cc1f55e7694d7e453c49033c75db1e6830` |

The outer vendor pin and inner template manifest must both validate before
either asset is listed, copied, or released. Missing, mismatched, unsafe,
duplicate, or symlinked entries disable the convenience catalog. Ordinary
path-based Weave and all Unravel behavior remain available. Release
construction refuses any template-integrity failure.

## Delivery boundary

Interactive **Start from a template** and headless `--list-templates` show the
release/upstream path, version, media type, bytes, SHA-256, and boundaries.
Listing and selecting write nothing. Copying requires a specific Word or
Markdown template plus a user-chosen file destination. A collision requires
the separate replacement action; symlink and non-regular destinations refuse.

After copy, the operator must complete and save the editable file, return to
Weave, select it, review producer preflight, correct missing scoring evidence
or explicitly approve only a permitted fallback, and type the named `WEAVE`
approval. Downloading or completing a template makes no Brightspace change.
A validated package build is not an import, activity attachment remains a
manual Brightspace step, and scoring is never silently invented.

## Independent-review repair

The pre-template TUI candidate received a NO-GO because the final `WEAVE`
approval was bound to a mutable path rather than the source bytes shown in
preflight. The repair uses `source.sha256` as the primary identity and
`source.extensions.bytes` as the secondary check.

Before build, the terminal copies only matching bytes into a private
controlled snapshot and supplies that binding to the orchestrator. The
orchestrator compares its own preflight, the bytes immediately before producer
invocation, and the producer receipt transport fingerprint. The terminal makes
one final snapshot/receipt comparison before claiming output. The original
lexical source remains the user-facing locator and is independently protected
from a containing `--force` output target. The effective producer-reported
source label is carried into the snapshot build and the private path is not
recorded.

If the source changes after the displayed preflight, interactive use starts
preflight again and clears prompt-granted fallback and named approvals.
Headless use exits `2`. Neither path starts a build from stale reviewed bytes.

The repair also:

- fails closed when receipt `emitted_files` is `null`, an object, or a string;
- reprompts or refuses an existing regular-file bundle target without a
  traceback;
- keeps Back as navigation at both fallback prompts;
- preserves lexical output and symlink safety;
- leaves legacy Unravel routing and non-template Weave artifacts unchanged.

## Release metadata and verification

`VERSION` is `1.2.0`; immutable v1.1.0 history and tags are not changed.
`coursecraft.bundle_release/1` advertises the two templates inside the Weave
capability, and `coursecraft.bundle_sbom/1` records the same two assets
alongside the unchanged locked dependency components. Each entry carries
upstream path, release path, version, media type, bytes, SHA-256, and the
scoring/import/attachment boundaries.

Current post-repair gates:

- vendor check and exact comparison to Workbench `ad08b1c…`: PASS;
- deterministic upstream template regeneration check: PASS;
- full bundle suite: **287 passed, 1 skipped** in 50.23 seconds;
- `git diff --check`: PASS.

These gates include all independent-review repairs: constant-stack template
navigation, complete validation of the parsed final receipt against the pinned
`coursecraft.run/1` schema, read-only template browsing, and fail-closed
destination and symlink-race handling.

## Superseded historical archive

Before the final independent-review repairs, an isolated temporary commit
produced:

- historical path: `dist/brightspace-rubric-bundle-v1.2.0.tar.gz`;
- bytes: **238,265**;
- SHA-256:
  `1c38d2ddd0e7d6de3db2439fe5dd281d6518f33d9121824a129e3e4095e8f30c`;
- historical matching sidecar:
  `dist/brightspace-rubric-bundle-v1.2.0.tar.gz.sha256`.

That archive and its successful deterministic double-build and exact archived
template-byte comparison predate both the recursion repair and complete final
receipt schema validation. They describe only that superseded snapshot and
must not be treated as current release evidence or as publishable v1.2.0
artifacts.

## Immutable release

The reviewed source tranche is commit
`6c1af0aacd746cd78fa30d6d654588338816dc04`, tagged `v1.2.0`. Two independent
builds from that exact commit were byte-identical. The published archive is:

- release:
  `https://github.com/timebeing92/brightspace-rubric-bundle/releases/tag/v1.2.0`;
- asset: `brightspace-rubric-bundle-v1.2.0.tar.gz`;
- bytes: **242,130**;
- SHA-256:
  `bb9036f6da074df2518b1b66647916741516190e2f3b711b4bfe39aa0acf72dc`;
- sidecar: `brightspace-rubric-bundle-v1.2.0.tar.gz.sha256`;
- published: `2026-07-26T01:19:56Z`.

The archive manifest identifies source commit `6c1af0a…`, version `1.2.0`, the
36-file Workbench distribution pin at `ad08b1c…`, and accepted producer
semantics at `7c51405…`. The SBOM records ten locked Python components and the
two editable template assets.

The remotely downloaded archive and sidecar were byte-identical to the two
local deterministic builds. The archived Word and Markdown assets also
matched the Workbench-owned bytes, sizes, and SHA-256 values recorded above.
