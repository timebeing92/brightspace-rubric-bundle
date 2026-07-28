# Rubric Loom — two-door terminal wizard

`scripts/rubric_loom_wizard.py` is the single operator shell for Unravel and
Weave. `launch_rubric_loom.command` is the single macOS launcher.

```bash
.venv/bin/python scripts/rubric_loom_wizard.py
```

Quiet startup checks cover both orchestrators, their contracts, and the
required Python packages. A guided launch starts by choosing a door:

- **Unravel** accepts a course export ZIP, unpacked export folder, or
  `rubrics_d2l.xml`. Its shallow export peek, DOCX/workbook/JSON options,
  progress board, partial-delivery behavior, and legacy CLI remain intact.
  After choosing the door, the operator can select one export or Bulk
  Unravel a parent folder of immediate ZIPs and unpacked export folders.
- **Weave** accepts supported DOCX, Markdown, and JSON authoring sources. It
  invokes producer preflight before writing, displays only producer-reported
  rubric counts, level labels, scoring sources, weight sources, and
  diagnostics, and requires the operator to type `WEAVE` before a build.
  Before source selection it can also show the exact release-pinned Word and
  Markdown intake templates. Merely listing or selecting one is read-only.

Both doors use `loom_progress.py` to consume the orchestrators'
`coursecraft.progress/1` events. Journey code supplies presentation flavor
and final result handling; the shared consumer knows no rubric semantics and
infers no artifacts.

## Landing and guided terminal flow

The normal terminal opens with the color Loom artwork and two explicit
choices: **UNRAVEL** or **WEAVE**. There is no launcher menu and no doctor
screen in front of those choices. Setup checks run quietly after the choice;
if a required package is missing, the Loom offers to install the pinned
runtime dependencies into its local `.venv`. The complete diagnostic
checklist remains available through `--doctor`.

After setup is known to be usable, the guided TUI performs a cached,
non-blocking check for the latest published GitHub release. It checks at most
once per day and says nothing when the installed version is current or GitHub
is unavailable. A newer release produces an informational card and an
optional “open release page” prompt. The checker never downloads, installs,
or replaces the current Loom.

Use `--check-for-updates` to force and report a check without beginning a
journey. Use `--no-update-check` to skip the automatic check for that launch.
Only safe `github.com/timebeing92/brightspace-rubric-bundle/releases/...`
links are offered.

After the landing page, the guided flow uses the same review-before-run
pattern as the Blueprint Wizard:

1. Choose what you want to do: read an existing export with **Unravel**, or
   package a completed rubric with **Weave**.
2. For Unravel, choose one export or a folder of exports. Select or drag the
   source file or folder into the terminal.
3. Read the source check. Weave also shows its producer preflight, including
   the adapter, rubric structure, scoring source, weight source, and any
   diagnostics.
4. Review one card containing the source, a recommended output name, the
   exact filenames, and the save folder.
5. Press Return to continue, or enter the number of the one item you want to
   change. You are not asked to rename or relocate anything unless you choose
   to.
6. Unravel starts from that review card. Weave retains a separate final
   safeguard: type `WEAVE` exactly to authorize package writing.

At each review card, `q` leaves without running and `b` returns to the
read-only source check. Error messages keep the user at the relevant screen
and say which numbered item to change.

### Bulk Unravel

Bulk Unravel is a guided-TUI coordinator over the unchanged single-export
producer. The selected folder is a batch container. Its immediate `.zip`
files and immediate child folders carrying `imsmanifest.xml` or
`rubrics_d2l.xml` are included; hidden entries, symlinks, ordinary files,
and unrelated folders are listed as ignored. Discovery does not recurse
through arbitrary nested containers.

A selected root that directly carries an export marker is refused as a
likely single unpacked export. Source names that collapse to the same safe
output label are also refused before writing. The review card shows the
inventory, shared output root, and DOCX choice once. Each source then runs
sequentially into `<label>__rubric_bundle`, with its own producer events,
artifacts, and log.

The final summary separates completed exports, exports with no rubric
evidence, failures, interruptions, and sources not attempted after an
interrupt. A partial batch exits `1`, a batch containing only rubric-free
exports exits `3`, and Ctrl-C exits `130`. Bulk mode currently belongs to
the guided TUI; the existing headless single-export contract is unchanged.
`--output-dir` can set the shared batch destination, while `--label` is
refused because every export requires its own collision-checked label.

## Non-interactive use

Every pre-R1 invocation remains Unravel:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py \
  --source path/to/export.zip --yes
```

Weave must be named and separately approved:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py \
  --door weave \
  --source path/to/rubric.md \
  --yes \
  --approve-weave \
  --output-dir output/example__weave_bundle
```

`--yes` never supplies missing rubric decisions. When the producer reports
missing scoring or weights, headless use must also name the corresponding
approval:

```bash
--allow-even-spacing
--allow-equal-weights
```

Those choices are shown before the build and recorded by the pinned producer.
Without them, preflight exits `2` and creates no output.

Headless template operations are separate from a build:

```bash
.venv/bin/python scripts/rubric_loom_wizard.py \
  --door weave --list-templates --plain

.venv/bin/python scripts/rubric_loom_wizard.py \
  --door weave \
  --copy-template rubric-weave-intake-template.md \
  --template-destination path/to/editable-rubric.md \
  --plain
```

Copy requires a user-chosen destination. Collisions refuse unless the separate
`--replace-template` action is present; symlink and non-regular destinations
always refuse. A successful copy reports the release/upstream path, version,
media type, bytes, and SHA-256 that passed both pin and manifest checks.

## Weave journey

1. Choose Weave.
2. Pick or drag a DOCX, Markdown, or JSON source, or choose **Start from a
   template** to inspect and explicitly copy a Word/Markdown starter.
3. When a template was copied, complete and save it, then return and select
   that saved copy; the copy action does not begin a build.
4. Read the pinned producer preflight.
5. Review reported rubrics, labels, scoring/weight sources, and diagnostics.
6. Make only the fallback decisions the producer requests.
7. Review the recommended output name, exact import ZIP name, and save folder;
   change only the numbered item that needs adjustment.
8. Type the named final approval `WEAVE`.
9. Watch the orchestrator's real six-step progress board.
10. Start with the Brightspace import ZIP; review normalized JSON, mapping,
   optional DOCX review, diagnostics, and the final receipt.

The success card states: “Nothing was imported. Activity attachment remains
manual.”

Delivery claims fail closed. The card loads the final `coursecraft.run/1`
receipt and checks every named artifact's path, byte count, and SHA-256.
Incomplete, interrupted, malformed-receipt, or checksum-mismatched runs claim
no delivery.

The final usable preflight also supplies the source-content binding:
`source.sha256` is primary and `source.extensions.bytes` is the secondary
sanity check. Before a terminal build, the selected source is copied into a
private controlled snapshot only if its current bytes still match. The
orchestrator compares the same binding to its own preflight and final producer
receipt. If the original changes, interactive use restarts preflight and
clears prompt-granted fallbacks; headless use exits `2`. No build starts from
stale reviewed bytes. The original source path remains the user-facing source
and remains protected from a containing `--force` output target.

## Interaction and terminal behavior

- Return accepts recommended names and locations. Numbered review-card actions
  open only the selected setting.
- `b`/`back` leaves an edit unchanged or returns a review card to the
  source/preflight. Back from the second fallback returns to the first scoring
  decision, while Back from the first returns to source/preflight.
- `q` leaves the landing or door router without running.
- Ctrl-C returns `130`; a running child receives SIGINT and no incomplete
  Weave artifact is presented as deliverable.
- Pipes, `--plain`, `NO_COLOR`, and `TERM=dumb` contain no ANSI escapes and
  use the same words and facts as the live board.
- TTY boards are display-paced; plain, piped, and `--brisk` runs are not.
- Remembered answers use `rubric_loom.state/2`, namespaced under `unravel` and
  `weave`. R3 flat state migrates only into Unravel.
- Weave logs use randomized, exclusive files under the local `output/logs`
  lane (or `RUBRIC_LOOM_LOG_DIR`); the logger refuses symlink targets before
  launching the producer.

The launcher performs the existing first-run `.venv` bootstrap and then opens
the art-led two-door TUI directly. Unravel and Weave demonstrations remain
inside their respective source choosers.

## Ownership boundary

`rubric_loom_weave.py` invokes `run_weave_bundle.py` for preflight and build.
It does not import DOCX, rubric authoring, package builder, D2L XML, adapter,
or normalization modules. Repository controls enforce that boundary.

The TUI does not claim a build was imported. It does not attach rubrics to
activities. Downloading or completing a template changes nothing in
Brightspace; building a package is not import. The TUI does not replace
authored labels or silently invent scores.
