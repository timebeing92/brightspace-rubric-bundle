# Rubric Loom — terminal wizard (R3)

The guided terminal surface for the **Unravel** door. R3 build authorized
by the operator 2026-07-21; register and voice per
`RUBRIC_LOOM_EXPERIENCE_FRAME.md` (operator-approved, canonical).

## Run it

```bash
.venv/bin/python scripts/rubric_loom_wizard.py
```

Double-clickable: `launch_rubric_loom.command` (macOS, family pattern —
the Blueprint Wizard and Archivist ship the same). It sets the Terminal
title, offers open/demonstration/doctor, holds the window open at the
end, and on a machine without a `.venv` offers first-time setup through
`scripts/bootstrap_env.py --dev` (Python 3.11–3.13). Piped invocations
of the launcher stay escape-free, like the wizard itself.

The wizard opens on a **landing card** — what the loom does, what you
bring, what you get, the privacy line, and how to steer — then walks
four phases: **The workshop** (doctor checklist — ends with "The loom is
threaded." when everything passes), **The source** (pick an export zip,
unpacked folder, or bare `rubrics_d2l.xml`; sources placed in `input/`
are offered automatically; the pinned synthetic fixture is available as
a labeled demonstration), a **peek card** reporting only what was
actually read (source kind, evidence presence, a shallow rubric count,
the manifest course title when one exists), **The commission** (label,
bundle folder, DOCX on/off, a named-action confirm), and
**The unravelling** (a live step board driven by the orchestrator's real
`coursecraft.progress/1` events). Success ends at "The cloth is bound ✦";
failure at "A thread snapped — the scroll below tells why." with the
failed step, the orchestrator's own message, any artifacts delivered
before the snap, and the log path.

## Finding your way

- A journey trail sits under every phase heading —
  `workshop › [source] › commission › unravelling` — with the current
  phase bracketed (and bold on color terminals), so "where am I" is
  always one glance away.
- Every prompt that has a previous screen accepts **`b`** (or `back`)
  and says so in its affordance: confirm → DOCX → bundle folder → label
  → source, one screen at a time. Stepping back to the source re-shows
  the peek card so it can be re-read; defaults keep your earlier
  answers.
- Each screen carries one quiet guidance line ("Return accepts a
  suggestion", "the loom asks once more before writing anything", …) —
  informative copy stays plain per the frame's consistency rule.
- Declining an occupied bundle folder returns to the folder prompt
  rather than quitting; `q` at the landing and `n` at the final confirm
  leave with "nothing was run."
- The landing and back navigation are interactive-only: `--brisk` skips
  the landing (and pacing), and `--yes`/piped runs are untouched — flags
  decide everything, exactly as before.

## Flags

| Flag | Meaning |
| --- | --- |
| `--source PATH` | export zip, unpacked folder, or `rubrics_d2l.xml` |
| `--output-dir DIR` | bundle destination (default `<repo>/output/<label>__rubric_bundle`, from any cwd — the lane the doctor vouches for) |
| `--label NAME` | artifact stem (default derived from the source) |
| `--no-docx` | skip the reviewer DOCX |
| `--yes` | accept defaults; no prompts (requires `--source`; flags decide, remembered answers never do — headless runs mirror the CLI exactly) |
| `--brisk` | skip the splash and the step-board pacing |
| `--plain` | plain text: no color, art, or in-place redraws (auto on pipes, `NO_COLOR`, `TERM=dumb`) |
| `--doctor` | run the workshop checks and exit |

The live board is display-paced (the family's established decision):
each completed step holds on screen ~1.1 s so its flavor line can
register, while the recorded per-step timings stay the events' real
numbers. `--brisk`, `--plain`, and piped runs are unpaced. The approved
voice lines keep their exact bytes in every mode — the plain pipe binds
the cloth with the same ✦.

Exit codes are the orchestrator's, passed through: 0 done (or declined
cleanly), 1 step failure, 2 usage/environment, 3 no rubric evidence;
130 on Ctrl-C ("The shuttle rests"). Remembered answers live in
`output/.rubric_loom_wizard_state.json` (gitignored; `RUBRIC_LOOM_STATE`
overrides for tests) and are consulted by interactive prompts only.

## Boundaries and decisions of record

- **CLI-and-events only** (ROADMAP R3): the wizard spawns
  `run_rubric_bundle.py --progress-events` and renders its events; it
  parses no D2L XML beyond presence detection. The peek's "rubrics
  sighted" count is a shallow byte scan (`<rubric` at a word boundary —
  which excludes the `<rubrics>` root and survives attribute-on-next-line
  openings); the orchestrator remains the only semantic reader. The
  course title comes from the IMS manifest when present (the Blueprint
  Wizard's peek precedent).
- **DOCX leads the results card** ("start here — the reviewer
  document"), with the workbook labeled "for editing workflows". The
  frame left which-leads open; the wizard resolves it in favor of the
  DOCX because the wizard is a human-review surface — editing workflows
  arrive knowing they want the workbook.
- **Partial delivery** (frame obligation): a DOCX-step failure names the
  workbook and contract JSON delivered by *this run's* completed steps
  (event-grounded — stale files from a previous run into the same folder
  are never claimed) and suggests `--no-docx`; nothing succeeded is
  hidden by what failed.
- **Component grammar** follows the Blueprint Wizard's kit
  (`loom_ui.py`, re-authored, not imported — cross-repo sharing awaits
  the ecosystem rule-of-three decision). Family palette logic: semantic
  colors shared, per-tool accent (loom thread rose, 256-color 168),
  accent on prompts only.
- **Weave is absent, not disabled**: the Weave door arrives with R2;
  the wizard offers only what runs today.

## R3 exit-condition evidence

`tests/test_rubric_loom_wizard.py::test_wizard_matches_cli_artifacts_on_the_synthetic_fixture`
runs the wizard non-interactively on `tests/fixtures/tiny_rubrics_export`
and the raw CLI side by side: identical artifact filename sets (the
wizard adds only its own `unravel_wizard.log`), byte-deterministic
rubrics JSON compared for full-document equality, and the guided PTY
journey test drives the same run interactively to the bound-cloth card.
