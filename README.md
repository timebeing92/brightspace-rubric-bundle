# Rubric Loom

<p align="center">
  <img src="docs/assets/rubric-loom-terminal.svg"
       alt="Color pixel-art Rubric Loom with warp threads, woven cloth, and a shuttle"
       width="620">
</p>

Rubric Loom helps you inspect, revise, and move Brightspace rubrics without
hand-editing D2L XML. It is purely deterministic software, running locally in
Python. No AI model reads or interprets your files, and your files are not
uploaded anywhere.

The Loom has two doors:

| Choose | Bring | Take away |
| --- | --- | --- |
| **Unravel** | One Brightspace course-export ZIP, one unpacked export folder, a bare `rubrics_d2l.xml`, or a folder containing several exports | A review DOCX, editing workbook, and structured JSON for each course |
| **Weave** | A completed rubric in a supported Word, Markdown, or JSON format | A validated, rubric-only Brightspace import ZIP, with review files and a run receipt |

Rubric Loom does not change Brightspace. You review every output. If you build
a Weave package, you import it yourself and manually attach the imported rubric
to the appropriate assignment, discussion, or quiz.

## Download the ready-to-run Loom

Most people should use the
[`brightspace-rubric-loom-runner` Releases page](https://github.com/timebeing92/brightspace-rubric-loom-runner/releases).

1. Open the newest release.
2. Under **Assets**, download `rubric-loom-managed-v<VERSION>.zip`.
3. Unzip it somewhere you can keep it, such as Documents or Applications.
4. Open the launcher for your operating system.

Do not use GitHub's green **Code > Download ZIP** button for an ordinary
installation. That button downloads one source repository, not the complete,
managed application. The managed release includes this engine, a compatible
runner, double-click launchers, private-environment setup, verified updates,
and rollback.

## First launch

Rubric Loom checks its Python environment and required packages as soon as it
opens—before it asks you to choose Unravel or Weave, and before it asks for a
file or folder path. If setup is needed, the launcher explains what is missing
and offers to install the pinned dependencies into the Loom's own private
environment. It does not install packages into your system Python.

### macOS

Open `Rubric Loom.command`.

macOS may block the launcher the first time because the release is not signed
through Apple's App Store or notarization service. If that happens:

1. Try to open `Rubric Loom.command` once, then dismiss the warning.
2. Open **System Settings > Privacy & Security**.
3. Scroll to **Security** and choose **Open Anyway** for Rubric Loom.
4. Authenticate with your password or Touch ID, then confirm **Open**.

Apple normally shows **Open Anyway** for about an hour after the blocked launch.
Use this exception only for the release you downloaded from this project's
GitHub page. See
[Apple's current instructions](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac).

### Windows

Open `Rubric Loom.bat`. If Windows shows a security or reputation prompt,
review that the file came from the project's GitHub release before choosing to
run it.

### Linux

Open a terminal in the unzipped folder and run:

```bash
bash rubric_loom_launcher.sh
```

## Choose a door

The landing screen makes the two jobs explicit.

### Unravel: read rubrics from Brightspace exports

Choose **Unravel** when the rubric already exists in Brightspace.

1. Choose **Single Unravel**, **Bulk Unravel**, or the built-in demonstration.
2. Drag in or type the path to your source.
3. Review what the Loom found and the filenames it proposes.
4. Press Return to accept the recommendations, or change only the numbered
   item that needs adjustment.
5. Run Unravel and review the success card.

A single source may be a course-export ZIP, an unpacked export folder, or a
bare `rubrics_d2l.xml`. Bulk Unravel accepts a parent folder whose immediate
contents are course-export ZIPs or unpacked export folders. It inventories the
batch once, then gives every course its own output folder and run log. One
failed or rubric-free export does not conceal the remaining results.

The result card reports how many rubrics were pulled, names each rubric, and
offers to open the containing folder.

### Weave: build a rubric-only import package

Choose **Weave** when you have a completed rubric that needs to become a
Brightspace package.

1. Select a supported Word, Markdown, or JSON rubric, try the demonstration,
   or copy a release-pinned intake template.
2. Read the producer preflight: rubric structure, level labels, scoring
   evidence, weights, and diagnostics.
3. Correct missing information in the source, or explicitly approve only a
   fallback the producer permits.
4. Review the proposed output folder and exact filenames.
5. Type `WEAVE` to authorize the build.
6. Review the validated import ZIP and its review and receipt files.

Weave never invents scoring silently. Its final receipt binds the package to
the exact source bytes you reviewed. A successful build is not an import:
import the ZIP yourself, then attach the rubric to activities manually in
Brightspace.

## What the software reads

A Brightspace course export is an ordinary ZIP file. Inside it,
`imsmanifest.xml` maps the package resources and course structure. D2L XML
files carry component-specific details; Rubric Loom works against the known
`rubrics_d2l.xml` structure and the Brightspace rubric dialect with
`schemaversion` v2011.

Each run follows declared schemas and explicit rules. The same source meets
the same checks every time. When a file does not match a supported structure,
the Loom reports that mismatch instead of guessing. Course exports contain
course content and structure, not learner records, but you should still handle
institutional course material according to your organization's policies.

## What Rubric Loom does not do

- It does not use AI or ask an LLM to interpret course material.
- It does not upload your source files.
- It does not import anything into Brightspace.
- It does not attach imported rubrics to activities.
- It does not silently invent rubric labels, levels, scoring, or weights.
- It does not replace human review.

## Updates, demonstrations, and user files

The guided Loom checks GitHub at most once per day for a newer published
release. Current, offline, and failed checks stay quiet. When an update exists,
the Loom can open the release page, but it never downloads or installs an
update automatically.

Each door includes a synthetic demonstration containing no course, learner, or
institutional data.

The managed runner keeps replaceable program versions separate from persistent
inputs, outputs, settings, and logs. See the runner README for its update and
rollback behavior.

## Run this producer repository directly

This repository is the technical producer used by the managed runner, the
CourseCraft Workshop, and headless integrations. Developers and reviewers can
clone it and run the bundle directly.

On macOS, double-click `launch_rubric_loom.command`. From a terminal, use
Python 3.11, 3.12, or 3.13:

```bash
python3.13 scripts/bootstrap_env.py --locked
.venv/bin/python scripts/rubric_loom_wizard.py
```

Substitute `python3.11` or `python3.12` when appropriate. The verbose
diagnostic checklist remains available separately:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py --doctor
```

For the complete guided and headless command reference, see
[`docs/RUBRIC_LOOM_WIZARD.md`](docs/RUBRIC_LOOM_WIZARD.md).

## Headless use

Unravel one export:

```bash
.venv/bin/python scripts/run_rubric_bundle.py path/to/export.zip
```

Preflight and build a Weave source:

```bash
.venv/bin/python scripts/run_weave_bundle.py rubric.md --preflight
.venv/bin/python scripts/run_weave_bundle.py rubric.md \
  --output-dir output/example__weave_bundle
```

The wizard also preserves the established non-interactive interface:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py \
  --source path/to/export.zip --yes

.venv/bin/python scripts/rubric_loom_wizard.py \
  --door weave \
  --source path/to/rubric.md \
  --yes \
  --approve-weave \
  --output-dir output/example__weave_bundle
```

`--yes` never supplies missing rubric decisions. Headless Weave must separately
name any permitted scoring or weight fallback.

## Release-pinned intake templates

Two Workbench-owned `v1` templates ship as exact pinned assets:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py \
  --door weave --list-templates --plain

.venv/bin/python scripts/rubric_loom_wizard.py \
  --door weave \
  --copy-template rubric-weave-intake-template.md \
  --template-destination path/to/my-rubric.md \
  --plain
```

Listing is read-only. Copying requires an explicit destination. Replacing an
existing regular file requires the separate `--replace-template` action;
symlink and non-regular destinations are refused. Copying or completing a
template changes nothing in Brightspace.

## Architecture and ownership

This repository is one portable producer with two doors that converge on the
same Brightspace rubric dialect:

- **Unravel** preserves authored wording and attribute values, then emits a
  review workbook, `coursecraft.rubrics/1` JSON validated against the vendored
  schema, and an optional reviewer DOCX.
- **Weave** accepts supported authoring sources and invokes the pinned
  Workbench producer for strict preflight, package construction, validation,
  normalized review outputs, and the final receipt.

`coursecraft_workbench` owns rubric contracts, extraction and build semantics,
and live-import evidence. This repository contains byte-pinned downstream
copies of the portable producer files. The immutable source ref and every
promoted file digest are recorded in `upstream/workbench_pin.json`.

The current distribution ref is Workbench
`60d81c9ce7d4518111443d03cf854b584644c3cc`; the accepted producer identity
and semantics trace to
`71552e912b79d73a00b4d70fd97bd32386fbe2a4`. Bundle-only code—its
orchestrators, terminal experience, synthetic journey, environment handling,
and release machinery—may be authored here. It must not silently fork upstream
rubric semantics.

The rubric extraction scripts also ship in `brightspace-blueprint-bundle` for
full blueprint runs. Both downstream copies trace to the same Workbench
source; semantic fixes land upstream first.

## Verify the source and product boundary

Check vendored producer bytes:

```bash
.venv/bin/python scripts/vendor_from_workbench.py --check
.venv/bin/python scripts/vendor_from_workbench.py \
  --compare-ref main \
  --workbench ../coursecraft_workbench
```

Run the full synthetic proof:

```bash
python3.13 scripts/bootstrap_env.py --dev
.venv/bin/python scripts/run_synthetic_journey.py
```

The journey weaves a package from a synthetic fixture, validates it, unravels
it through the canonical extractor, and confirms that rubric names survive the
round trip. Its receipt is written to
`output/synthetic_journey/journey_receipt.json`.

Run all repository checks:

```bash
.venv/bin/python scripts/vendor_from_workbench.py --check
.venv/bin/python -m pytest
```

## Build a bundle release asset

```bash
.venv/bin/python scripts/make_release_asset.py --ref <tag-or-commit>
```

The builder exports one explicit ref and writes a reproducible
`dist/brightspace-rubric-bundle-v<VERSION>.tar.gz` with a checksum sidecar.
The archive carries:

- `RELEASE_MANIFEST.json` (`coursecraft.bundle_release/1`) with source,
  contract, runtime, Unravel, and Weave capability records;
- deterministic `SBOM.json` (`coursecraft.bundle_sbom/1`) derived from
  `requirements-lock.txt`, including the pinned template assets.

Missing or mismatched producer files, schemas, templates, runtime markers,
preflight behavior, progress behavior, or receipt behavior prevent release
construction.

## Repository map

| Path | Purpose |
| --- | --- |
| `scripts/rubric_loom_wizard.py` | Guided two-door terminal application |
| `scripts/run_rubric_bundle.py` | Unravel orchestrator |
| `scripts/run_weave_bundle.py` | Weave orchestrator |
| `scripts/run_synthetic_journey.py` | Deterministic round-trip proof |
| `scripts/make_release_asset.py` | Reproducible bundle release builder |
| `upstream/workbench_pin.json` | Immutable provenance and byte-digest map |
| `docs/REPOSITORY_BOUNDARY.md` | Ownership decision record |
| `ROADMAP.md` | Phased product plan |

Rubric Loom is licensed under
[AGPL-3.0-or-later](LICENSE). Existing bundle-family commercial terms and
attribution notices are preserved in the repository and release artifacts.
