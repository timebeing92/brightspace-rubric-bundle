# Rubric Loom — user-facing experience frame

Status: design frame only. Nothing here authorizes a build; R3 (terminal
wizard) and R4 (hosted bench) in `ROADMAP.md` gate the work. The register
proposal below needs operator approval before any user-facing surface
adopts it.

## Register proposal: the loom

A rubric is a woven grid — criteria are the warp, performance levels the
weft. The proposed register:

- Product: **Rubric Loom**.
- Doors: **Unravel** (a finished course's rubrics come apart into readable
  cloth — workbook, contract JSON, reviewer document) and **Weave** (an
  authored contract becomes an import-ready package).
- Voice samples, in the family of the Blueprint Wizard's "the workshop" and
  Quiz Binder's bindery: "The loom is threaded." (setup complete), "Reading
  the weave…" (extraction running), "The cloth is bound ✦" (artifacts
  delivered), "A thread snapped — the scroll below tells why." (failure
  card).
- Consistency rule: phases carry the diegetic voice; informative copy (what
  you bring, what you get, menu paths) stays plain. Color and pacing follow
  the established terminal design decisions (accent color for prompts only,
  flavor lines held long enough to register, `--brisk`/plain-pipe escape
  hatches).

Open for the operator: does the loom register carry your voice, or should
this surface take a different metaphor? Recorded as an open question in the
boundary doc.

## The two-door journey

Both doors share one spine: pick a source → the tool peeks and says what it
sees → confirm particulars → live step board → results card with a primary
deliverable marked "start here".

**Unravel** (exists today as CLI): source = export zip / folder /
`rubrics_d2l.xml`. Peek card should name the course (when a manifest is
present) and the rubric count before committing to the run. Results card:
workbook, contract JSON, reviewer DOCX, with the DOCX as the primary
deliverable for human review and the workbook primary for editing workflows
— which one leads is an open design question.

**Weave** (R2): source = flat markdown / JSON contract (later DOCX). Peek
card previews parsed rubrics and flags normalization decisions before
building. Results card: package zip as primary deliverable, plus the
mapping and normalized-contract receipts. The attachment story (rubrics do
not self-bind to activities on import) must be stated plainly on the
results card — this is the single most surprising fact for colleagues.

## Terminal wizard (R3 frame)

- Co-located in this repo, consuming only the orchestrator CLI and
  `coursecraft.progress/1` events — the CLI-and-events boundary the
  Blueprint Wizard and Quiz Binder established.
- Reuse the runner's proven component grammar (doctor checklist, peek card,
  options card, live step board, results card, graceful Ctrl-C, `--yes`)
  rather than inventing a new one; whether code is shared or re-authored
  follows the ecosystem launcher/rule-of-three decision, not this repo.
- Progress contract: `coursecraft.progress/1` as vendored. If Weave needs
  verdict vocabulary the contract lacks (normalization decisions,
  attachment reminders), propose a sibling contract upstream first — the
  quiz pillar's `quiz_progress/1` is the precedent.

## Hosted bench (R4 frame)

- One bench in the existing workshop Space hub (benches are cheap, URLs are
  not — the established hub decision), lit only when this repo has a pinned
  release the Space can consume.
- Same privacy gate as the Blueprint bench: exports are institutional
  content; ephemeral processing, no retention, and the public/private
  posture is an explicit operator decision at bench time.
- Web code stays presentation-only over the pinned release (web-track drift
  governance rule).

## States and copy skeleton (both surfaces)

| State | Obligation |
| --- | --- |
| Empty / awaiting source | Say what the tool accepts and where in Brightspace the export comes from. |
| Peek | Report only what was actually read (course title, rubric count); never imply parsing depth that hasn't happened. |
| Running | Real step completion drives the indicator; flavor never outruns the events. |
| Partial | If extraction succeeds and the DOCX fails, deliver what exists and say exactly what is missing (the blueprint partial-delivery precedent). |
| Failure | Name the failed step, show the log path, offer the doctor. |
| Done | Primary deliverable marked; counts stated ("3 rubrics, 1 diagnostic"); next human action named (review the DOCX / import the zip / attach in Brightspace). |
