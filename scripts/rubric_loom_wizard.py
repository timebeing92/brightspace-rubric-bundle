#!/usr/bin/env python3
"""Rubric Loom — terminal wizard for the Unravel door (roadmap R3).

A guided surface over ``run_rubric_bundle.py``. The wizard consumes only
the orchestrator CLI and its ``coursecraft.progress/1`` events — the
CLI-and-events boundary the Blueprint Wizard and Quiz Binder established.
It never parses D2L XML beyond presence detection (a shallow byte scan at
the peek card), never infers artifacts (delivery claims come from this
run's events plus on-disk existence), and composes the pinned pipeline
rather than reimplementing any of it.

Register and voice follow docs/RUBRIC_LOOM_EXPERIENCE_FRAME.md, approved
by the operator on 2026-07-21; the R3 build was authorized by the
operator on 2026-07-21. Phases carry the diegetic voice; informative
copy stays plain; the accent color appears on prompts only.

Exit codes: 0 done (or declined cleanly), 1 step failure, 2 usage or
environment error, 3 no rubric evidence in the source, 130 interrupted.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import loom_art
import loom_ui
import run_rubric_bundle as unravel

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
ORCHESTRATOR = SCRIPTS / "run_rubric_bundle.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "tiny_rubrics_export"
INPUT_LANE = REPO_ROOT / "input"
LOG_NAME = "unravel_wizard.log"

# Remembered answers live in the gitignored output/ lane; the env override
# exists so tests never touch the operator's remembered choices.
STATE_PATH = Path(
    os.environ.get(
        "RUBRIC_LOOM_STATE",
        str(REPO_ROOT / "output" / ".rubric_loom_wizard_state.json"),
    )
)

# Display-only pacing for the live board (the family's established
# decision: the Blueprint Wizard holds each completed step on screen long
# enough for its flavor line to register). Real step timings still come
# from the events and are shown truthfully; only the display is paced.
# --brisk and plain/piped modes run unpaced.
MIN_STEP_SECONDS = 1.1

# Approved voice lines (docs/RUBRIC_LOOM_EXPERIENCE_FRAME.md — verbatim,
# in every mode: plain pipes keep the same words, glyph included).
VOICE_THREADED = "The loom is threaded."
VOICE_READING = "Reading the weave…"
VOICE_BOUND = "The cloth is bound ✦"
VOICE_SNAPPED = "A thread snapped — the scroll below tells why."

# Per-step flavor in the loom register (tunable per the frame; the
# extraction line is the approved sample and stays verbatim).
FLAVOR = {
    unravel.STEP_LOCATE: "Feeling for the weave's edge…",
    unravel.STEP_EXTRACT: VOICE_READING,
    unravel.STEP_VALIDATE: "Counting warp and weft against the pattern…",
    unravel.STEP_DOCX: "Pressing the cloth for review…",
}

# Which orchestrator step produces which artifact — used so delivery
# claims are grounded in THIS run's completed steps, never in whatever
# bytes a previous run left in the same folder.
PRODUCED_BY = {
    "workbook": unravel.STEP_EXTRACT,
    "contract JSON": unravel.STEP_EXTRACT,
    "reviewer DOCX": unravel.STEP_DOCX,
}

ACCEPTS_LINE = (
    "The loom accepts a Brightspace course export zip, an unpacked export "
    "folder, or a bare rubrics_d2l.xml (Course Admin > Import/Export/Copy "
    "Components > Export produces the zip)."
)

PHASES = ("workshop", "source", "commission", "unravelling")


def trail(term: loom_ui.Term, current: str) -> str:
    """A one-line journey marker under each phase heading. The brackets
    carry the position, so plain mode loses nothing."""
    parts = []
    for name in PHASES:
        if name == current:
            parts.append(term.bold(f"[{name}]"))
        else:
            parts.append(term.dim(name))
    return "  " + " › ".join(parts)


def guidance(term: loom_ui.Term, text: str) -> None:
    """One quiet what-do-I-do-here line. Informative copy stays plain."""
    print("  " + term.dim(text))


def landing(term: loom_ui.Term) -> bool:
    """The welcome screen: what this is, what you bring, what you get,
    and how to steer. Returns False when the operator leaves here."""
    rows: list[tuple[str, str]] = [
        ("", "The Rubric Loom unravels the rubrics inside a Brightspace"),
        ("", "course export into readable cloth."),
        ("", ""),
        ("you bring", "a course export zip, an unpacked export folder,"),
        (" ", "or a bare rubrics_d2l.xml"),
        ("you get", "a reviewer DOCX, an editing workbook (XLSX), and a"),
        (" ", "validated contract (JSON), together in one bundle folder"),
        ("", ""),
        ("", "Everything runs on this machine. Nothing is sent anywhere;"),
        ("", "nothing touches Brightspace."),
    ]
    print(loom_ui.card(term, "Welcome to the loom", rows))
    print(trail(term, "workshop"))
    guidance(
        term,
        "Return accepts a suggestion · b steps back a screen · Ctrl-C "
        "leaves cleanly at any point",
    )
    reply = loom_ui.prompt_text(term, "Return opens the workshop (q leaves)")
    if isinstance(reply, str) and reply.strip().lower() in {"q", "quit"}:
        print("  nothing was run.")
        return False
    return True


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def load_state() -> dict:
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # remembering answers is a courtesy, never a failure


def relative_display(path: Path) -> str:
    """Prefer a path the operator can read at a glance."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def parse_typed_path(raw: str) -> Path | None:
    """Accept pasted and dragged path forms: plain, quoted, and
    backslash-escaped (what macOS Terminal produces on drag-and-drop)."""
    text = raw.strip()
    if not text:
        return None
    if (text[0] == text[-1] == "'") or (text[0] == text[-1] == '"'):
        text = text[1:-1]
    elif "\\" in text:
        try:
            parts = shlex.split(text)
            if parts:
                text = parts[0] if len(parts) == 1 else " ".join(parts)
        except ValueError:
            pass
    return Path(text).expanduser()


def wrap_rows(text: str, width: int = 58) -> list[tuple[str, str]]:
    import textwrap

    return [("", line) for line in textwrap.wrap(text, width=width)] or [("", text)]


# ---------------------------------------------------------------------------
# Peek (presence detection only — the orchestrator is the only semantic
# reader of rubric XML; this scan exists so the peek card reports what was
# actually looked at, per the frame's Peek obligation)
# ---------------------------------------------------------------------------
def source_kind(source: Path) -> str:
    if source.is_file() and source.name == unravel.RUBRIC_XML_NAME:
        return "bare rubrics_d2l.xml"
    if source.is_file() and source.suffix.lower() == ".zip":
        return "course export zip"
    if source.is_dir():
        return "unpacked export folder"
    return "unrecognized"


def _rubric_xml_bytes(source: Path) -> tuple[bytes | None, bool]:
    """(rubric xml bytes, source readable). Among multiple matches the
    shallowest path wins — the same preference the pinned extractor
    applies after unzip, so the peek reads the file the run will use."""
    try:
        if source.is_file() and source.name == unravel.RUBRIC_XML_NAME:
            return source.read_bytes(), True
        if source.is_file() and source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                names = sorted(
                    (n for n in archive.namelist() if Path(n).name == unravel.RUBRIC_XML_NAME),
                    key=lambda n: (len(Path(n).parts), n),
                )
                return (archive.read(names[0]) if names else None), True
        if source.is_dir():
            matches = sorted(
                source.rglob(unravel.RUBRIC_XML_NAME),
                key=lambda p: (len(p.parts), str(p)),
            )
            return (matches[0].read_bytes() if matches else None), True
    except zipfile.BadZipFile:
        return None, False
    except (OSError, KeyError):
        return None, True
    return None, True


def _manifest_bytes(source: Path) -> bytes | None:
    try:
        if source.is_file() and source.suffix.lower() == ".zip":
            with zipfile.ZipFile(source) as archive:
                names = sorted(
                    (n for n in archive.namelist() if Path(n).name == "imsmanifest.xml"),
                    key=lambda n: (len(Path(n).parts), n),
                )
                return archive.read(names[0]) if names else None
        if source.is_dir():
            manifests = sorted(
                source.rglob("imsmanifest.xml"),
                key=lambda p: (len(p.parts), str(p)),
            )
            return manifests[0].read_bytes() if manifests else None
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    return None


def manifest_title(source: Path) -> str:
    """Course title from the IMS manifest, when one is present (the
    Blueprint Wizard's peek precedent; namespace-agnostic, best-effort)."""
    data = _manifest_bytes(source)
    if not data:
        return ""
    try:
        root = ET.fromstring(data)
        org = next(
            (el for el in root.iter() if el.tag.split("}", 1)[-1] == "organization"),
            None,
        )
        if org is None:
            return ""
        title = next(
            (child for child in org if child.tag.split("}", 1)[-1] == "title"), None
        )
        return (title.text or "").strip() if title is not None else ""
    except ET.ParseError:
        return ""


def peek(source: Path) -> dict:
    """Report only what was actually read: kind, readability, evidence
    presence, a shallow count of ``<rubric`` element openings, and the
    manifest title.

    The count is presence-detection-grade: a byte regex for ``<rubric``
    followed by a word boundary (the fixture opens elements across
    newlines, and the root element is ``<rubrics>`` — both are handled by
    the boundary). No semantic parsing happens here.
    """
    data, readable = _rubric_xml_bytes(source)
    return {
        "kind": source_kind(source),
        "readable": readable,
        "evidence": data is not None,
        "sighted": len(re.findall(rb"<rubric\b", data)) if data is not None else None,
        "title": manifest_title(source),
    }


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------
def module_present(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def default_bundle_dir(label: str) -> Path:
    """Repo-anchored default so the doctor's output-lane check describes
    the lane the run will actually use, from any cwd (AGENTS.md keeps
    generated artifacts in the repo's gitignored output/ lane)."""
    return REPO_ROOT / "output" / f"{label}__rubric_bundle"


def run_doctor(term: loom_ui.Term) -> tuple[bool, bool]:
    """Print the checklist; return (core_ok, docx_ok)."""
    version = ".".join(str(part) for part in sys.version_info[:3])
    checks: list[tuple[str, bool, str, bool]] = [
        # (label, ok, detail, core)
        ("Python interpreter", True, version, True),
        ("jsonschema (contract validation)", module_present("jsonschema"), "", True),
        ("openpyxl (workbook writer)", module_present("openpyxl"), "", True),
        ("python-docx (reviewer document)", module_present("docx"), "", False),
        ("Unravel orchestrator", ORCHESTRATOR.is_file(), "scripts/run_rubric_bundle.py", True),
        (
            "coursecraft.rubrics/1 schema",
            unravel.RUBRICS_SCHEMA_PATH.is_file(),
            "",
            True,
        ),
    ]
    output_ok = True
    try:
        (REPO_ROOT / "output").mkdir(parents=True, exist_ok=True)
    except OSError:
        output_ok = False
    checks.append(
        ("output lane writable", output_ok, relative_display(REPO_ROOT / "output"), True)
    )

    core_ok = True
    docx_ok = True
    for label, ok, detail, core in checks:
        status = "ok" if ok else ("bad" if core else "warn")
        print(loom_ui.status_line(term, status, label, detail))
        if not ok and core:
            core_ok = False
        if not ok and not core:
            docx_ok = False
    if core_ok:
        print("  " + term.italic(term.secondary(VOICE_THREADED)))
    else:
        print(
            "  the loom cannot run until the checks above pass "
            "(install requirements.txt into .venv)"
        )
    if not docx_ok:
        print(
            loom_ui.status_line(
                term,
                "warn",
                "the reviewer DOCX will be offered as off (--no-docx)",
            )
        )
    return core_ok, docx_ok


# ---------------------------------------------------------------------------
# Source selection and cards
# ---------------------------------------------------------------------------
def input_lane_candidates() -> list[Path]:
    if not INPUT_LANE.is_dir():
        return []
    found: list[Path] = []
    try:
        for child in sorted(INPUT_LANE.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_file() and child.suffix.lower() == ".zip":
                found.append(child)
            elif child.is_file() and child.name == unravel.RUBRIC_XML_NAME:
                found.append(child)
            elif child.is_dir():
                found.append(child)
    except OSError:
        return []
    return found[:9]


def pick_source(term: loom_ui.Term, remembered: str) -> Path | None:
    print(ACCEPTS_LINE)
    candidates = input_lane_candidates()
    remembered_path = Path(remembered) if remembered else None
    options: list[tuple[str, str]] = []
    default = "path"
    for index, path in enumerate(candidates, start=1):
        options.append((str(index), f"{relative_display(path)}  ({source_kind(path)})"))
        if remembered_path is not None and path == remembered_path:
            default = str(index)
    options.append(("path", "type a path"))
    options.append(
        ("demo", f"the pinned synthetic fixture ({relative_display(FIXTURE)})")
    )
    if default == "path" and remembered_path == FIXTURE:
        default = "demo"
    choice = loom_ui.choose(
        term, "Which source should the loom unravel?", options, default=default
    )
    if choice == "demo":
        return FIXTURE
    if choice == "path":
        for _ in range(3):
            raw = loom_ui.prompt_text(term, "Path to the export", default=remembered)
            candidate = parse_typed_path(raw)
            if candidate is None:
                print("  nothing chosen; the loom stays idle")
                return None
            if candidate.exists():
                return candidate
            print(loom_ui.status_line(term, "bad", f"not found: {raw}"))
        return None
    return candidates[int(choice) - 1]


def peek_card(term: loom_ui.Term, source: Path, seen: dict) -> None:
    if not seen["readable"]:
        evidence_text = "not a readable zip archive"
    elif seen["evidence"]:
        evidence_text = "rubrics_d2l.xml present"
    else:
        evidence_text = "no rubrics_d2l.xml found"
    rows: list[tuple[str, str]] = [
        ("source", relative_display(source)),
        ("kind", seen["kind"]),
        ("rubric evidence", evidence_text),
    ]
    if seen["sighted"] is not None:
        rows.append(("rubrics sighted", str(seen["sighted"])))
    rows.append(("course title", seen["title"] or "(no manifest in this source)"))
    print(loom_ui.card(term, "What the loom can see", rows))


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------
def artifact_paths(out_dir: Path, label: str, use_docx: bool) -> dict[str, Path]:
    paths = {
        "workbook": out_dir / f"{label}__rubrics.xlsx",
        "contract JSON": out_dir / f"{label}__rubrics.json",
    }
    if use_docx:
        paths["reviewer DOCX"] = out_dir / f"{label}__rubrics.docx"
    return paths


def delivered_this_run(
    ok_steps: list[str], out_dir: Path, label: str, use_docx: bool
) -> list[tuple[str, Path]]:
    """Artifacts THIS run's completed steps produced and that exist on
    disk. Stale files from a previous run into the same folder are never
    claimed (their producing step did not complete in this run)."""
    delivered = []
    for name, path in artifact_paths(out_dir, label, use_docx).items():
        if PRODUCED_BY.get(name) in ok_steps and path.is_file():
            delivered.append((name, path))
    return delivered


def run_unravel(
    term: loom_ui.Term,
    source: Path,
    out_dir: Path,
    label: str,
    use_docx: bool,
    *,
    min_step_seconds: float,
) -> int:
    command = [
        sys.executable,
        str(ORCHESTRATOR),
        str(source),
        "--output-dir",
        str(out_dir),
        "--label",
        label,
        "--progress-events",
    ]
    if not use_docx:
        command.append("--no-docx")

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / LOG_NAME
    log = log_path.open("w", encoding="utf-8")
    log.write("rubric_loom_wizard run\n")
    log.write("command: " + " ".join(command) + "\n")
    log.write("started: " + time.strftime("%Y-%m-%d %H:%M:%S") + "\n---\n")

    board: loom_ui.StepBoard | None = None
    run_end: dict | None = None
    ok_steps: list[str] = []
    failed_step: str | None = None
    failed_message = ""
    steps: list[str] = []
    display_started = 0.0
    last_tick = 0.0
    paced = (not term.plain) and min_step_seconds > 0

    pending: collections.deque = collections.deque()

    def apply(event: dict) -> None:
        nonlocal board, run_end, failed_step, failed_message, steps, display_started
        kind = event.get("event")
        if kind == "run_start":
            steps = [str(step) for step in event.get("steps", [])]
            board = loom_ui.StepBoard(term, steps, flavor=FLAVOR)
        elif kind == "step_start" and board is not None:
            display_started = time.monotonic()
            board.step_start(int(event.get("index", 0)))
        elif kind == "step_end" and board is not None:
            index = int(event.get("index", 0))
            status = str(event.get("status", "error"))
            board.step_end(index, status, float(event.get("seconds") or 0.0))
            if 1 <= index <= len(steps):
                if status == "ok":
                    ok_steps.append(steps[index - 1])
                else:
                    failed_step = steps[index - 1]
                    failed_message = str(event.get("message") or "")
        elif kind == "run_end":
            run_end = event
        # Unknown event kinds are ignored, never narrated.

    def pump() -> None:
        """Apply queued events; completed steps are held on screen for
        min_step_seconds (display-only — recorded timings stay real)."""
        nonlocal last_tick
        while pending:
            event = pending[0]
            if (
                paced
                and event.get("event") == "step_end"
                and board is not None
                and time.monotonic() - display_started < min_step_seconds
            ):
                break
            apply(pending.popleft())
        now = time.monotonic()
        if board is not None and now - last_tick >= 0.1:
            board.tick()
            last_tick = now

    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    interrupted = False
    reader_done = False
    try:
        while not reader_done or pending:
            if not reader_done:
                ready, _, _ = select.select([proc.stdout], [], [], 0.08)
                if ready:
                    line = proc.stdout.readline()
                    if not line:
                        reader_done = True
                    else:
                        log.write(line)
                        stripped = line.strip()
                        if stripped:
                            try:
                                pending.append(json.loads(stripped))
                            except json.JSONDecodeError:
                                # progress/1 consumer rule: non-JSON lines
                                # pass through.
                                if board is not None:
                                    board.output_line(stripped)
                                else:
                                    print("  " + term.dim(stripped))
                elif proc.poll() is not None:
                    reader_done = True
            else:
                time.sleep(0.05)
            pump()
    except KeyboardInterrupt:
        interrupted = True
        try:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            proc.terminate()
    finally:
        return_code = proc.wait()
        if board is not None and not interrupted:
            board.finish()
        log.write(f"---\nchild exit: {return_code}\n")
        log.close()

    if interrupted:
        print()
        rows: list[tuple[str, str]] = []
        rows.append(("completed", ", ".join(ok_steps) if ok_steps else "no step had finished"))
        rows.append(("bundle", relative_display(out_dir)))
        rows += wrap_rows(
            "The folder may hold artifacts from the completed steps; they are "
            "safe to keep or delete. Run the loom again to weave a fresh set."
        )
        rows.append(("log", relative_display(log_path)))
        print(loom_ui.card(term, "The shuttle rests — interrupted", rows))
        return 130

    if return_code == 0 and run_end is not None and run_end.get("status") == "ok":
        results_card(term, run_end, out_dir, label, use_docx, log_path)
        return 0

    failure_card(
        term,
        return_code,
        run_end,
        failed_step,
        failed_message,
        ok_steps,
        out_dir,
        label,
        use_docx,
        log_path,
    )
    return return_code if return_code else 1


def results_card(
    term: loom_ui.Term,
    run_end: dict,
    out_dir: Path,
    label: str,
    use_docx: bool,
    log_path: Path,
) -> None:
    summary = run_end.get("summary") or {}
    rubrics = int(summary.get("rubrics") or 0)
    diagnostics = int(summary.get("diagnostics") or 0)
    outputs = run_end.get("outputs") or {}
    paths = artifact_paths(out_dir, label, use_docx)
    # A run_end of ok implies at least one rubric: the pinned extractor
    # refuses zero-rubric sources outright (its own "No <rubric> elements
    # found" failure), so no empty-success state exists to narrate.

    print()
    counts = f"{rubrics} rubric(s), {diagnostics} diagnostic(s)"
    rows: list[tuple[str, str]] = [("unraveled", counts)]
    if use_docx and outputs.get("rubrics_docx"):
        rows.append(("start here", f"{relative_display(paths['reviewer DOCX'])}  — the reviewer document"))
    rows.append(("workbook", f"{relative_display(paths['workbook'])}  — for editing workflows"))
    rows.append(("contract", relative_display(paths["contract JSON"])))
    rows.append(("bundle", relative_display(out_dir)))
    rows.append(("log", relative_display(log_path)))
    if use_docx and outputs.get("rubrics_docx"):
        next_action = "Next: review the DOCX; edit in the workbook if changes are needed."
    else:
        next_action = "Next: open the workbook to review and edit the rubrics."
    rows += wrap_rows(next_action)
    print(loom_ui.card(term, VOICE_BOUND, rows))


def failure_card(
    term: loom_ui.Term,
    return_code: int,
    run_end: dict | None,
    failed_step: str | None,
    failed_message: str,
    ok_steps: list[str],
    out_dir: Path,
    label: str,
    use_docx: bool,
    log_path: Path,
) -> None:
    step = failed_step or ""
    message = failed_message
    if run_end and run_end.get("status") == "error":
        issues = run_end.get("issues") or []
        if issues and isinstance(issues[0], dict):
            step = step or str(issues[0].get("step") or "")
            message = message or str(issues[0].get("message") or "")
        message = message or str(run_end.get("message") or "")
    print()
    print("  " + (term.bad(VOICE_SNAPPED) if not term.plain else VOICE_SNAPPED))
    rows: list[tuple[str, str]] = []
    rows.append(("failed step", step or "(before the first step)"))
    rows += wrap_rows(message or f"the orchestrator exited {return_code}")
    delivered = delivered_this_run(ok_steps, out_dir, label, use_docx)
    if delivered:
        rows.append(("", ""))
        rows.append(("delivered before the snap", ""))
        for name, path in delivered:
            rows.append((f"  {name}", relative_display(path)))
        rows += wrap_rows(
            "The loom did not finish; keep what helps, delete what doesn't."
        )
    if return_code == 3:
        rows += wrap_rows(ACCEPTS_LINE)
    if step == unravel.STEP_DOCX:
        rows += wrap_rows(
            "The extraction itself succeeded. Re-run with --no-docx to keep "
            "the workbook and contract without the reviewer document."
        )
    rows.append(("log", relative_display(log_path)))
    rows.append(("doctor", "rubric_loom_wizard.py --doctor checks the workshop"))
    print(loom_ui.card(term, "the scroll", rows))


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="export zip, unpacked folder, or rubrics_d2l.xml")
    parser.add_argument("--output-dir", type=Path, help="bundle destination (default: <repo>/output/<label>__rubric_bundle)")
    parser.add_argument("--label", help="artifact stem (default: derived from the source name)")
    parser.add_argument("--no-docx", action="store_true", help="skip the reviewer DOCX render")
    parser.add_argument("--yes", action="store_true", help="accept defaults; no prompts (requires --source)")
    parser.add_argument("--brisk", action="store_true", help="skip the splash and the step-board pacing")
    parser.add_argument("--plain", action="store_true", help="plain text: no color, art, or in-place redraws")
    parser.add_argument("--doctor", action="store_true", help="run the workshop checks and exit")
    return parser.parse_args(argv if argv is not None else sys.argv[1:])


def _docx_note(use_docx: bool, args, docx_ok: bool) -> str:
    if use_docx:
        return "yes"
    if args.no_docx:
        return "no (--no-docx)"
    if not docx_ok:
        return "no (python-docx is not installed)"
    return "no"


def _start_unravel(
    term: loom_ui.Term,
    args,
    source: Path,
    out_dir: Path,
    label: str,
    use_docx: bool,
) -> int:
    save_state({"source": str(source), "docx": use_docx})
    print(loom_ui.heading(term, "The unravelling", "4 of 4"))
    print(trail(term, "unravelling"))
    guidance(term, "The board is live - real steps, real timings. Ctrl-C stops cleanly.")
    min_step = 0.0 if (args.brisk or term.plain) else MIN_STEP_SECONDS
    return run_unravel(
        term, source, out_dir, label, use_docx, min_step_seconds=min_step
    )


def _show_source_peek(term: loom_ui.Term, source: Path) -> dict:
    seen = peek(source)
    peek_card(term, source, seen)
    guidance(
        term,
        "If this looks right, continue - the loom asks once more before "
        "writing anything.",
    )
    return seen


def _thin_weave_note(seen: dict) -> str | None:
    if not seen["evidence"]:
        return "no rubric evidence sighted in this source"
    if seen["sighted"] == 0:
        return "rubric evidence is present but no rubric entries were sighted"
    return None


def _run_headless(term: loom_ui.Term, args, docx_ok: bool) -> int:
    """--yes path: flags decide, remembered answers never do (the
    family's --yes rule); headless runs mirror the CLI exactly."""
    source = args.source.expanduser()
    print(loom_ui.heading(term, "The source", "2 of 4"))
    print(trail(term, "source"))
    print(loom_ui.status_line(term, "ok", f"source: {relative_display(source)}"))
    if not source.exists():
        print(loom_ui.status_line(term, "bad", f"source not found: {source}"))
        return 2
    seen = _show_source_peek(term, source)
    note = _thin_weave_note(seen)
    if note:
        print(loom_ui.status_line(term, "warn", note))

    print(loom_ui.heading(term, "The commission", "3 of 4"))
    print(trail(term, "commission"))
    label = (
        unravel.sanitize_label(args.label) if args.label
        else unravel.default_label(source)
    )
    out_dir = (
        args.output_dir if args.output_dir is not None
        else default_bundle_dir(label)
    )
    if out_dir.exists() and any(out_dir.iterdir()):
        print(
            loom_ui.status_line(
                term,
                "warn",
                f"{relative_display(out_dir)} is not empty; matching "
                "artifacts will be overwritten",
            )
        )
    use_docx = not args.no_docx and docx_ok
    rows = [
        ("source", relative_display(source)),
        ("label", label),
        ("bundle", relative_display(out_dir)),
        ("reviewer DOCX", _docx_note(use_docx, args, docx_ok)),
    ]
    print(loom_ui.card(term, "Ready to unravel", rows))
    loom_ui.confirm(
        term,
        f"Start the unravel into {relative_display(out_dir)}?",
        default=True,
        assume_yes=True,
    )
    return _start_unravel(term, args, source, out_dir, label, use_docx)


def _run_interactive(term: loom_ui.Term, args, docx_ok: bool) -> int:
    """The reversible journey: source → label → bundle → DOCX → confirm,
    with ``b`` stepping back one screen at every prompt."""
    state = load_state()
    source: Path | None = None
    peeked_for: Path | None = None
    label: str | None = None
    out_dir: Path | None = None
    out_dir_typed = False
    use_docx: bool | None = None
    step = "source"
    prev = ""

    while True:
        if step == "source":
            print(loom_ui.heading(term, "The source", "2 of 4"))
            print(trail(term, "source"))
            guidance(
                term,
                "Point the loom at an export. A number picks from the "
                "list; Return takes the suggestion.",
            )
            if args.source is not None and source is None:
                source = args.source.expanduser()
                print(
                    loom_ui.status_line(
                        term, "ok", f"source: {relative_display(source)}"
                    )
                )
            elif args.source is not None:
                # Backed into a flag-pinned source: show it again so the
                # peek can be re-read; the flag stays the source of truth.
                print(
                    loom_ui.status_line(
                        term, "ok", f"source: {relative_display(source)}"
                    )
                )
            else:
                remembered = str(source) if source else str(state.get("source", ""))
                picked = pick_source(term, remembered)
                if picked is None:
                    print("  nothing was run.")
                    return 0
                source = picked
            if not source.exists():
                print(
                    loom_ui.status_line(
                        term, "bad", f"source not found: {source}"
                    )
                )
                return 2
            seen = _show_source_peek(term, source)
            note = _thin_weave_note(seen)
            if note and source != peeked_for:
                print(loom_ui.status_line(term, "warn", note))
                proceed = loom_ui.confirm(
                    term,
                    "Ask the loom to try anyway? (it will refuse if there "
                    "is truly nothing to unravel)",
                    default=False,
                )
                if not proceed:
                    print("  nothing was run.")
                    return 0
            peeked_for = source
            prev, step = "source", "label"

        elif step == "label":
            if prev == "source":
                print(loom_ui.heading(term, "The commission", "3 of 4"))
                print(trail(term, "commission"))
                guidance(
                    term,
                    "Name the cloth and where it goes. Return accepts "
                    "each suggestion; b steps back.",
                )
            default_label = label or (
                unravel.sanitize_label(args.label) if args.label
                else unravel.default_label(source)
            )
            reply = loom_ui.prompt_text(
                term,
                "Label for the artifacts",
                default=default_label,
                allow_back=True,
            )
            if reply is loom_ui.BACK:
                prev, step = "label", "source"
                continue
            label = unravel.sanitize_label(str(reply))
            prev, step = "label", "bundle"

        elif step == "bundle":
            if out_dir_typed and out_dir is not None:
                default_dir = out_dir
            elif args.output_dir is not None:
                default_dir = args.output_dir
            else:
                default_dir = default_bundle_dir(label)
            reply = loom_ui.prompt_text(
                term, "Bundle folder", default=str(default_dir), allow_back=True
            )
            if reply is loom_ui.BACK:
                prev, step = "bundle", "label"
                continue
            typed = parse_typed_path(str(reply))
            out_dir = typed if typed is not None else default_dir
            out_dir_typed = str(out_dir) != str(default_bundle_dir(label))
            if out_dir.exists() and any(out_dir.iterdir()):
                print(
                    loom_ui.status_line(
                        term,
                        "warn",
                        f"{relative_display(out_dir)} is not empty; "
                        "matching artifacts will be overwritten",
                    )
                )
                if not loom_ui.confirm(
                    term, "Weave into it anyway?", default=False
                ):
                    continue  # stay here; choose a different folder
            prev, step = "bundle", "docx"

        elif step == "docx":
            if args.no_docx or not docx_ok:
                use_docx = False
                prev, step = "docx", "confirm"
                continue
            default_docx = (
                use_docx if use_docx is not None
                else bool(state.get("docx", True))
            )
            reply = loom_ui.confirm(
                term,
                "Render the reviewer DOCX?",
                default=default_docx,
                allow_back=True,
            )
            if reply is loom_ui.BACK:
                prev, step = "docx", "bundle"
                continue
            use_docx = bool(reply)
            prev, step = "docx", "confirm"

        elif step == "confirm":
            rows = [
                ("source", relative_display(source)),
                ("label", label),
                ("bundle", relative_display(out_dir)),
                ("reviewer DOCX", _docx_note(use_docx, args, docx_ok)),
            ]
            print(loom_ui.card(term, "Ready to unravel", rows))
            guidance(
                term,
                "Return starts it · b steps back · n leaves without running",
            )
            reply = loom_ui.confirm(
                term,
                f"Start the unravel into {relative_display(out_dir)}?",
                default=True,
                allow_back=True,
            )
            if reply is loom_ui.BACK:
                prev, step = "confirm", "docx"
                continue
            if not reply:
                print("  nothing was run.")
                return 0
            return _start_unravel(term, args, source, out_dir, label, use_docx)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    term = loom_ui.Term(plain=args.plain)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    if args.doctor:
        loom_art.banner(term)
        print(loom_ui.heading(term, "The workshop", "doctor"))
        core_ok, _ = run_doctor(term)
        return 0 if core_ok else 2

    if args.yes and args.source is None:
        print(
            "rubric_loom_wizard: --yes needs --source PATH (defaults answer "
            "prompts; the source has no default)",
            file=sys.stderr,
        )
        return 2
    headless = args.yes and args.source is not None
    if not interactive and not headless:
        print(
            "rubric_loom_wizard: not a terminal; pass --source PATH --yes "
            "(and optionally --output-dir/--label/--no-docx) to run "
            "non-interactively",
            file=sys.stderr,
        )
        return 2

    try:
        if interactive and not args.brisk and not term.plain:
            loom_art.splash(term, animate=True)
        else:
            loom_art.banner(term)

        if interactive and not args.yes and not args.brisk:
            if not landing(term):
                return 0

        # -- The workshop -------------------------------------------------
        print(loom_ui.heading(term, "The workshop", "1 of 4"))
        print(trail(term, "workshop"))
        guidance(term, "The loom checks its own equipment; nothing has run yet.")
        core_ok, docx_ok = run_doctor(term)
        if not core_ok:
            return 2

        if args.yes:
            return _run_headless(term, args, docx_ok)
        return _run_interactive(term, args, docx_ok)
    except KeyboardInterrupt:
        print("\n  interrupted — nothing else was run.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
