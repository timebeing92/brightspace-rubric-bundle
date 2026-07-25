# Wave 5 — TUI incorporation

Status: candidate implemented; focused verification green

## Shape

Rubric Loom remains one product:

- `scripts/rubric_loom_wizard.py` — shared shell and door router
- `scripts/rubric_loom_weave.py` — bounded Weave presentation journey
- `scripts/loom_progress.py` — shared progress/cancellation consumer
- `scripts/loom_ui.py` and `scripts/loom_art.py` — shared terminal kit
- `launch_rubric_loom.command` — one launcher

Legacy `--source PATH --yes` remains Unravel. Non-interactive Weave requires
`--door weave --yes --approve-weave`; missing source decisions are never
filled by `--yes`.

## Producer boundary

Weave preflight and build are subprocess calls to
`scripts/run_weave_bundle.py`. The journey displays only fields in the
producer preflight: rubric counts and names, level labels, scoring and weight
sources, and diagnostics. It has no DOCX, Markdown-table, authoring-contract,
adapter, builder, or D2L XML parser.

Fallbacks are opt-in through `--allow-even-spacing` and
`--allow-equal-weights` or equivalent interactive confirmations prompted
only after the producer asks for them. The operator must then type `WEAVE`
before any build.

## Artifact truth

The import ZIP leads the success card. Normalized JSON, mapping and optional
review reports, diagnostics, and receipt follow. The journey opens the final
`coursecraft.run/1` receipt and verifies each claimed artifact path, size,
SHA-256, and producer role. A missing, escaped, unreceipted, role-mismatched,
or modified artifact is not presented as delivered.

The card ends with:

> Nothing was imported. Activity attachment remains manual.

Failed and interrupted Weave runs claim no delivery, even when partial or
stale bytes exist.

The TUI makes relative paths independent of its repo-root child process but
does not resolve symlink components before invoking the producer. The
producer's symlinked replacement-target refusal therefore remains identical
between direct CLI and TUI use. Weave logs use a controlled local log lane,
random names, and exclusive no-follow creation.

## Shared behavior

Both doors now use the same progress-event process consumer. Unravel
regression behavior remains covered. State is `rubric_loom.state/2` with
separate `unravel` and `weave` namespaces and migration of the former flat
shape only into Unravel.

Focused coverage includes CLI/TUI equality, producer preflight, named
approval, fallback receipt recording, Back/quit/Ctrl-C, invalid and occupied
destinations, success/failure/interruption, tampered receipt claims,
plain/piped/`NO_COLOR`/`TERM=dumb`, state isolation, launcher syntax, and the
existing Unravel PTY journey.
