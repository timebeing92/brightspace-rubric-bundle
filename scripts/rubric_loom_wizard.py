#!/usr/bin/env python3
"""Rubric Loom — two-door terminal wizard for Unravel and Weave.

A shared shell routes to the existing Unravel journey over
``run_rubric_bundle.py`` or the bounded Weave journey over
``run_weave_bundle.py``. Both doors consume only orchestrator CLIs and
``coursecraft.progress/1`` events. The TUI owns no rubric semantics.

Register and voice follow docs/RUBRIC_LOOM_EXPERIENCE_FRAME.md, approved
by the operator on 2026-07-21; the R3 build was authorized by the
operator on 2026-07-21. Phases carry the diegetic voice; informative
copy stays plain; the accent color appears on prompts only.

Exit codes: 0 done (or declined cleanly), 1 step failure, 2 usage or
environment error, 3 no rubric evidence in the source, 130 interrupted.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import webbrowser
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import loom_art
import loom_progress
import loom_ui
import release_check
import run_rubric_bundle as unravel
import rubric_loom_templates as templates

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
ORCHESTRATOR = SCRIPTS / "run_rubric_bundle.py"
WEAVE_ORCHESTRATOR = SCRIPTS / "run_weave_bundle.py"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "tiny_rubrics_export"
INPUT_LANE = REPO_ROOT / "input"
LOG_NAME = "unravel_wizard.log"
RUNTIME_REQUIREMENTS = REPO_ROOT / "requirements-lock.txt"
VERSION_PATH = REPO_ROOT / "VERSION"
RELEASE_CACHE_PATH = Path(
    os.environ.get(
        "RUBRIC_LOOM_RELEASE_CACHE",
        str(REPO_ROOT / "output" / "update-cache" / "release_check.json"),
    )
)
SUPPORTED_PYTHON = (3, 11), (3, 14)
RUNTIME_MODULES = (
    ("jsonschema", "jsonschema"),
    ("openpyxl", "openpyxl"),
    ("docx", "python-docx"),
)

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
    "Bring a Brightspace course-export ZIP, an unpacked export folder, or a "
    "bare rubrics_d2l.xml. In Brightspace, Course Admin > Import/Export/Copy "
    "Components > Export Course Components creates the ZIP."
)

PHASES = ("source", "review", "unravelling")


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
    print(loom_ui.paragraph(term, text, dim=True))


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


def door_state(state: dict, door: str) -> dict:
    """Read namespaced state, with the R3 flat shape treated as Unravel."""
    doors = state.get("doors")
    if isinstance(doors, dict) and isinstance(doors.get(door), dict):
        return dict(doors[door])
    if door == "unravel":
        return {
            key: state[key]
            for key in ("source", "docx")
            if key in state
        }
    return {}


def save_door_state(door: str, values: dict) -> None:
    state = load_state()
    existing_unravel = door_state(state, "unravel")
    doors = state.get("doors")
    if not isinstance(doors, dict):
        doors = {}
    if existing_unravel and "unravel" not in doors:
        doors["unravel"] = existing_unravel
    doors[door] = dict(values)
    save_state(
        {
            "schema": "rubric_loom.state/2",
            "last_door": door,
            "doors": doors,
        }
    )


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


def python_supported() -> bool:
    version = sys.version_info[:2]
    return SUPPORTED_PYTHON[0] <= version < SUPPORTED_PYTHON[1]


def default_bundle_dir(label: str) -> Path:
    """Repo-anchored default for the gitignored output lane."""
    return REPO_ROOT / "output" / f"{label}__rubric_bundle"


def output_lane_write_anchor(output_lane: Path) -> tuple[Path, bool]:
    """Inspect the lane or nearest existing parent without creating either."""

    current = output_lane
    while True:
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if current == current.parent:
                return current, False
            current = current.parent
            continue
        except OSError:
            return current, False
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            return current, False
        return current, os.access(current, os.W_OK | os.X_OK)


def environment_checks() -> list[tuple[str, bool, str, bool]]:
    """Return setup facts as (label, ok, detail, blocks_core)."""
    version = ".".join(str(part) for part in sys.version_info[:3])
    checks: list[tuple[str, bool, str, bool]] = [
        ("Python 3.11–3.13", python_supported(), version, True),
        ("jsonschema (contract validation)", module_present("jsonschema"), "", True),
        ("openpyxl (workbook writer)", module_present("openpyxl"), "", True),
        ("python-docx (reviewer document)", module_present("docx"), "", False),
        ("Unravel orchestrator", ORCHESTRATOR.is_file(), "scripts/run_rubric_bundle.py", True),
        (
            "Weave orchestrator",
            WEAVE_ORCHESTRATOR.is_file(),
            "scripts/run_weave_bundle.py",
            True,
        ),
        (
            "coursecraft.rubrics/1 schema",
            unravel.RUBRICS_SCHEMA_PATH.is_file(),
            "",
            True,
        ),
        (
            "coursecraft.rubric_authoring/1 schema",
            (
                REPO_ROOT
                / "workspace/reference/schemas/rubrics/rubric_authoring_schema.json"
            ).is_file(),
            "",
            True,
        ),
    ]
    output_lane = REPO_ROOT / "output"
    output_anchor, output_ok = output_lane_write_anchor(output_lane)
    output_detail = relative_display(output_lane)
    if output_anchor != output_lane:
        output_detail += (
            f" (nearest existing parent: {relative_display(output_anchor)})"
        )
    checks.append(
        ("output lane writable", output_ok, output_detail, True)
    )
    return checks


def run_doctor(term: loom_ui.Term) -> tuple[bool, bool]:
    """Print the full diagnostic checklist; return (core_ok, docx_ok)."""
    checks = environment_checks()

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


def missing_runtime_packages() -> list[str]:
    return [
        package
        for module, package in RUNTIME_MODULES
        if not module_present(module)
    ]


def local_venv_python() -> Path:
    if os.name == "nt":
        return REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    return REPO_ROOT / ".venv" / "bin" / "python"


def running_in_local_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == local_venv_python().resolve()
    except OSError:
        return False


def repair_runtime_dependencies(
    term: loom_ui.Term,
    packages: list[str],
    *,
    assume_yes: bool,
) -> bool:
    """Offer one bounded repair, using the lock file.

    The ordinary launcher already runs inside the repo-local environment. A
    direct system-Python launch creates that same local environment and
    restarts into it rather than installing packages globally.
    """
    target = (
        "the local .venv"
        if running_in_local_venv()
        else "a local .venv inside this Rubric Loom folder"
    )
    print()
    print(
        loom_ui.card(
            term,
            "One-time setup needed",
            [
                ("Missing", ", ".join(packages)),
                ("Install into", target),
                ("Source", "requirements-lock.txt"),
                ("", ""),
                ("", "Nothing is installed outside this Rubric Loom folder."),
            ],
        )
    )
    if not loom_ui.confirm(
        term,
        "Install the required Python packages now?",
        default=True,
        assume_yes=assume_yes,
    ):
        print("  setup was skipped; nothing was run.")
        return False

    if running_in_local_venv():
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-r",
            str(RUNTIME_REQUIREMENTS),
        ]
    else:
        command = [
            sys.executable,
            str(SCRIPTS / "bootstrap_env.py"),
            "--locked",
        ]
    print(
        loom_ui.status_line(
            term,
            "run",
            "Installing the Rubric Loom dependencies",
            target,
        )
    )
    result = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if result.returncode != 0:
        print(
            loom_ui.status_line(
                term,
                "bad",
                "Setup did not finish",
                "the installer output above says why",
            )
        )
        return False

    if not running_in_local_venv():
        python = local_venv_python()
        if not python.is_file():
            print(
                loom_ui.status_line(
                    term, "bad", "Setup did not create the local Python environment"
                )
            )
            return False
        print(loom_ui.status_line(term, "ok", "Environment ready", "restarting"))
        os.execv(
            str(python),
            [str(python), str(Path(__file__).resolve()), *sys.argv[1:]],
        )
        return False  # pragma: no cover - os.execv replaces this process

    importlib.invalidate_caches()
    if missing_runtime_packages():
        print(
            loom_ui.status_line(
                term,
                "bad",
                "Setup completed but required packages are still unavailable",
            )
        )
        return False
    print(loom_ui.status_line(term, "ok", "Environment ready"))
    return True


def ensure_environment(
    term: loom_ui.Term,
    *,
    assume_yes: bool,
) -> tuple[bool, bool]:
    """Quietly verify setup, offering repair only when packages are missing."""
    packages = missing_runtime_packages()
    if packages and not repair_runtime_dependencies(
        term, packages, assume_yes=assume_yes
    ):
        # A missing python-docx alone remains a supported reduced Unravel
        # environment. Core package failures must stop.
        core_missing = any(name != "python-docx" for name in packages)
        if core_missing:
            return False, False

    checks = environment_checks()
    failures = [
        (label, detail)
        for label, ok, detail, core in checks
        if core and not ok
    ]
    docx_ok = module_present("docx")
    if failures:
        rows = [(label, detail or "missing") for label, detail in failures]
        rows.extend(
            [
                ("", ""),
                ("Details", "rubric_loom_wizard.py --doctor"),
            ]
        )
        print()
        print(loom_ui.card(term, "The Loom cannot start yet", rows))
        return False, docx_ok
    if not docx_ok:
        print(
            loom_ui.status_line(
                term,
                "warn",
                "Reviewer DOCX unavailable",
                "Unravel will still create the workbook and JSON",
            )
        )
    return True, docx_ok


def installed_version() -> str:
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def report_release_check(
    term: loom_ui.Term,
    *,
    force: bool,
    offer_open: bool,
) -> None:
    """Report a newer published release without blocking the current Loom."""
    current = installed_version()
    status = release_check.check_latest_release(
        current_version=current,
        cache_path=RELEASE_CACHE_PATH,
        force=force,
    )
    if status.state == "unavailable":
        if force:
            print(
                loom_ui.card(
                    term,
                    "Release check unavailable",
                    [
                        ("Installed", current or "(version file unavailable)"),
                        (
                            "",
                            "GitHub could not be checked. The installed Loom "
                            "is still usable.",
                        ),
                    ],
                )
            )
        return

    if not status.update_available:
        if force:
            title = (
                "This checkout is newer than the latest published release"
                if status.state == "ahead"
                else "Rubric Loom is up to date"
            )
            print(
                loom_ui.card(
                    term,
                    title,
                    [
                        ("Installed", f"v{current}"),
                        ("Latest release", f"v{status.latest_version}"),
                    ],
                )
            )
        return

    if not force and not release_check.notice_is_due(
        RELEASE_CACHE_PATH,
        latest_version=status.latest_version,
    ):
        return

    rows = [
        ("Installed", f"v{current}"),
        ("Available", term.bold(f"v{status.latest_version}")),
    ]
    if status.release_name and status.release_name != status.latest_tag:
        rows.append(("Release", status.release_name))
    rows.extend(
        [
            ("Page", status.release_url),
            ("", ""),
            ("", "The current Loom remains usable. Nothing was installed."),
        ]
    )
    print()
    print(loom_ui.card(term, "A newer Rubric Loom release is available", rows))
    release_check.mark_notified(
        RELEASE_CACHE_PATH,
        latest_version=status.latest_version,
    )
    if not offer_open:
        return
    if loom_ui.confirm(term, "Open the GitHub release page?", default=False):
        try:
            opened = webbrowser.open(status.release_url)
        except OSError:
            opened = False
        if not opened:
            print("  Open this page: " + status.release_url)


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
    print(loom_ui.paragraph(term, ACCEPTS_LINE))
    print()
    while True:
        candidates = input_lane_candidates()
        remembered_path = Path(remembered) if remembered else None
        options: list[tuple[str, str]] = []
        default = "path"
        for index, path in enumerate(candidates, start=1):
            options.append(
                (
                    str(index),
                    f"Use {relative_display(path)}  ({source_kind(path)})",
                )
            )
            if remembered_path is not None and path == remembered_path:
                default = str(index)
        options.append(("path", "Enter or drag a different file or folder path"))
        options.append(
            (
                "demo",
                f"Try the built-in demonstration  ({relative_display(FIXTURE)})",
            )
        )
        options.append(("q", "Leave without running"))
        if default == "path" and remembered_path == FIXTURE:
            default = "demo"
        choice = loom_ui.choose(
            term,
            "Where is the course export you want to read?",
            options,
            default=default,
            allow_back=True,
        )
        if choice is loom_ui.BACK or choice == "q":
            return None
        if choice == "demo":
            return FIXTURE
        if choice == "path":
            while True:
                print()
                guidance(
                    term,
                    "Tip: drag the ZIP or folder into this window to paste its path.",
                )
                print()
                raw = loom_ui.prompt_text(
                    term,
                    "Course export path",
                    default=remembered,
                    allow_back=True,
                )
                if raw is loom_ui.BACK:
                    break
                candidate = parse_typed_path(str(raw))
                if candidate is None:
                    print("  no source was selected.")
                    return None
                if candidate.exists():
                    return candidate
                print(
                    loom_ui.status_line(
                        term,
                        "bad",
                        f"I could not find that file or folder: {raw}",
                    )
                )
            continue
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
    print(loom_ui.card(term, "Course export check", rows))


def _review_docx_text(use_docx: bool, args, docx_ok: bool) -> str:
    if args.no_docx:
        return "no — disabled by --no-docx"
    if not docx_ok:
        return "unavailable — python-docx is not installed"
    if use_docx:
        return "yes — recommended starting point for review"
    return "no — workbook and JSON only"


def unravel_review_rows(
    source: Path,
    label: str,
    out_dir: Path,
    use_docx: bool,
    args,
    docx_ok: bool,
) -> list[tuple[str, str]]:
    rows = [
        ("1. Source", relative_display(source)),
        ("2. Output name", label),
    ]
    if use_docx:
        rows.append(("   Review file", f"{label}__rubrics.docx"))
    rows.extend(
        [
            ("   Edit file", f"{label}__rubrics.xlsx"),
            ("   Data file", f"{label}__rubrics.json"),
            ("3. Save folder", relative_display(out_dir)),
            ("4. Review DOCX", _review_docx_text(use_docx, args, docx_ok)),
            ("", ""),
            ("", "Nothing is written until you press Return to start."),
        ]
    )
    return rows


def unravel_destination_ready(term: loom_ui.Term, out_dir: Path) -> bool:
    try:
        mode = out_dir.lstat().st_mode
    except FileNotFoundError:
        return True
    except OSError:
        print(
            loom_ui.status_line(
                term, "bad", "The save folder could not be inspected."
            )
        )
        return False
    if stat.S_ISLNK(mode):
        print(
            loom_ui.status_line(
                term, "bad", "Choose a save folder that is not a symbolic link."
            )
        )
        return False
    if not stat.S_ISDIR(mode):
        print(
            loom_ui.status_line(
                term,
                "bad",
                "The save location is an existing file, not a folder.",
            )
        )
        return False
    if any(out_dir.iterdir()):
        return bool(
            loom_ui.confirm(
                term,
                "This folder already contains files. Replace matching Loom files?",
                default=False,
            )
        )
    return True


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
    progress = loom_progress.consume(
        term,
        command,
        log_path,
        log_title="rubric_loom_wizard unravel run",
        flavor=FLAVOR,
        min_step_seconds=min_step_seconds,
    )
    return_code = progress.return_code
    run_end = progress.run_end
    ok_steps = progress.ok_steps
    failed_step = progress.failed_step
    failed_message = progress.failed_message

    if progress.interrupted:
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
    rows: list[tuple[str, str]] = [("Read from export", counts)]
    if use_docx and outputs.get("rubrics_docx"):
        rows.append(
            (
                "start here",
                f"{relative_display(paths['reviewer DOCX'])}  — review document",
            )
        )
    rows.append(
        (
            "Editing workbook",
            f"{relative_display(paths['workbook'])}  — structured editing",
        )
    )
    rows.append(("Structured JSON", relative_display(paths["contract JSON"])))
    rows.append(("Output folder", relative_display(out_dir)))
    rows.append(("Run log", relative_display(log_path)))
    if use_docx and outputs.get("rubrics_docx"):
        next_action = (
            "Next: review the DOCX. Use the workbook when you need to revise "
            "rubric content in a structured form."
        )
    else:
        next_action = "Next: open the workbook to review and revise the rubrics."
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
    rows.append(("doctor", "rubric_loom_wizard.py --doctor shows setup diagnostics"))
    print(loom_ui.card(term, "the scroll", rows))


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--door",
        choices=("unravel", "weave"),
        help="choose a door (legacy --source/--yes defaults to unravel)",
    )
    parser.add_argument("--source", type=Path, help="export zip, unpacked folder, or rubrics_d2l.xml")
    parser.add_argument("--output-dir", type=Path, help="bundle destination (default: <repo>/output/<label>__rubric_bundle)")
    parser.add_argument("--label", help="artifact stem (default: derived from the source name)")
    parser.add_argument("--no-docx", action="store_true", help="skip the reviewer DOCX render")
    parser.add_argument("--yes", action="store_true", help="accept defaults; no prompts (requires --source)")
    parser.add_argument("--brisk", action="store_true", help="skip the splash and the step-board pacing")
    parser.add_argument("--plain", action="store_true", help="plain text: no color, art, or in-place redraws")
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="show the full setup diagnostic checklist and exit",
    )
    parser.add_argument(
        "--check-for-updates",
        action="store_true",
        help="check GitHub for the latest published Rubric Loom release, then exit",
    )
    parser.add_argument(
        "--no-update-check",
        action="store_true",
        help="skip the once-daily automatic release check",
    )
    template_actions = parser.add_mutually_exclusive_group()
    template_actions.add_argument(
        "--list-templates",
        action="store_true",
        help="list exact release-pinned Weave templates without writing",
    )
    template_actions.add_argument(
        "--copy-template",
        choices=tuple(templates.EXPECTED_MEDIA_TYPES),
        help="copy one exact release-pinned Weave template",
    )
    parser.add_argument(
        "--template-destination",
        type=Path,
        help="required explicit file destination for --copy-template",
    )
    parser.add_argument(
        "--replace-template",
        action="store_true",
        help="explicitly replace an existing regular template destination",
    )
    parser.add_argument(
        "--approve-weave",
        action="store_true",
        help="named final approval for a headless Weave write",
    )
    parser.add_argument("--allow-even-spacing", action="store_true")
    parser.add_argument("--allow-equal-weights", action="store_true")
    parser.add_argument("--context-dir", type=Path)
    parser.add_argument("--source-label")
    parser.add_argument("--orgunit-identifier")
    parser.add_argument("--default-nav")
    parser.add_argument("--default-homepage")
    parser.add_argument("--title")
    parser.add_argument("--keyword")
    parser.add_argument("--manifest-identifier")
    parser.add_argument("--resource-prefix")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--step-timeout", type=float, default=900.0)
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
    save_door_state("unravel", {"source": str(source), "docx": use_docx})
    print(loom_ui.heading(term, "The unravelling", "3 of 3"))
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
        "The source has only been inspected. Review the proposed output names "
        "and save folder next.",
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
    print(loom_ui.heading(term, "The source", "1 of 3"))
    print(trail(term, "source"))
    print(loom_ui.status_line(term, "ok", f"source: {relative_display(source)}"))
    if not source.exists():
        print(loom_ui.status_line(term, "bad", f"source not found: {source}"))
        return 2
    seen = _show_source_peek(term, source)
    note = _thin_weave_note(seen)
    if note:
        print(loom_ui.status_line(term, "warn", note))

    print(loom_ui.heading(term, "Review the output", "2 of 3"))
    print(trail(term, "review"))
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
        ("output name", label),
        ("save folder", relative_display(out_dir)),
        ("review DOCX", _docx_note(use_docx, args, docx_ok)),
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
    """A source check followed by one editable review card.

    Recommended names are chosen automatically. The operator sees the exact
    folder and filenames before writing, and only opens a separate prompt for
    a value they choose to change.
    """
    state = door_state(load_state(), "unravel")
    source: Path | None = None
    peeked_for: Path | None = None
    label: str | None = None
    out_dir: Path | None = None
    use_docx: bool | None = None
    automatic_label = True
    automatic_folder = args.output_dir is None
    step = "source"

    while True:
        if step == "source":
            print(loom_ui.heading(term, "The source", "1 of 3"))
            print(trail(term, "source"))
            print()
            guidance(
                term,
                "Choose the Brightspace export to read. This check is read-only.",
            )
            print()
            if args.source is not None:
                source = args.source.expanduser()
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
            recommended = (
                unravel.sanitize_label(args.label)
                if args.label
                else unravel.default_label(source)
            )
            if label is None or automatic_label:
                label = recommended
            if use_docx is None:
                use_docx = (
                    not args.no_docx
                    and docx_ok
                    and bool(state.get("docx", True))
                )
            if out_dir is None or automatic_folder:
                out_dir = (
                    args.output_dir
                    if args.output_dir is not None
                    else default_bundle_dir(label)
                )
            step = "review"

        elif step == "review":
            assert source is not None
            assert label is not None
            assert out_dir is not None
            assert use_docx is not None
            print(loom_ui.heading(term, "Review the output", "2 of 3"))
            print(trail(term, "review"))
            guidance(
                term,
                "Recommended names are ready. Press Return to start, or change "
                "only the item you need.",
            )
            print(
                loom_ui.card(
                    term,
                    "Ready to unravel",
                    unravel_review_rows(
                        source, label, out_dir, use_docx, args, docx_ok
                    ),
                )
            )
            reply = loom_ui.review_choice(
                term,
                "Start Unravel?",
                choices=("1", "2", "3", "4"),
                allow_back=True,
            )
            if reply == "q":
                print("  nothing was run.")
                return 0
            if reply is loom_ui.BACK or reply == "1":
                if args.source is None:
                    source = None
                step = "source"
                continue
            if reply == "2":
                changed = loom_ui.prompt_text(
                    term,
                    "Output name (used at the start of each filename)",
                    default=label,
                    allow_back=True,
                )
                if changed is not loom_ui.BACK:
                    label = unravel.sanitize_label(str(changed))
                    automatic_label = False
                    if automatic_folder:
                        out_dir = default_bundle_dir(label)
                continue
            if reply == "3":
                changed = loom_ui.prompt_text(
                    term,
                    "Save folder",
                    default=str(out_dir),
                    allow_back=True,
                )
                if changed is not loom_ui.BACK:
                    parsed = parse_typed_path(str(changed))
                    if parsed is not None:
                        out_dir = parsed
                        automatic_folder = False
                continue
            if reply == "4":
                if args.no_docx or not docx_ok:
                    print(
                        loom_ui.status_line(
                            term,
                            "warn",
                            _review_docx_text(False, args, docx_ok),
                        )
                    )
                else:
                    changed = loom_ui.confirm(
                        term,
                        "Create the reviewer DOCX?",
                        default=use_docx,
                        allow_back=True,
                    )
                    if changed is not loom_ui.BACK:
                        use_docx = bool(changed)
                continue
            if not unravel_destination_ready(term, out_dir):
                guidance(term, "Enter 3 on the review card to choose another folder.")
                continue
            return _start_unravel(term, args, source, out_dir, label, use_docx)


def choose_door(term: loom_ui.Term, state: dict) -> str:
    remembered = str(state.get("last_door") or "unravel")
    if remembered not in {"unravel", "weave"}:
        remembered = "unravel"
    print()
    print(
        loom_ui.card(
            term,
            "Choose what you want to do",
            [
                ("UNRAVEL", "Read rubrics from an existing Brightspace export."),
                ("  Bring", "A course-export ZIP, unpacked export, or rubrics_d2l.xml."),
                ("  Get", "A review DOCX, editing workbook, and structured JSON."),
                ("", ""),
                ("WEAVE", "Build a rubric-only Brightspace import package."),
                ("  Bring", "A completed Word, Markdown, or JSON rubric."),
                ("  Get", "A validated import ZIP with review and run receipts."),
                ("", ""),
                ("", "Rubric Loom has no AI component. Both doors run locally."),
                ("", "You will review exact outputs before anything is written."),
            ],
        )
    )
    return str(
        loom_ui.choose(
            term,
            "What do you want to do?",
            [
                (
                    "unravel",
                    "UNRAVEL — read rubrics from a course export",
                ),
                (
                    "weave",
                    "WEAVE — build an import package from a completed rubric",
                ),
                ("q", "Leave the loom without running"),
            ],
            default=remembered,
        )
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    term = loom_ui.Term(plain=args.plain)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    template_action = bool(args.list_templates or args.copy_template)

    if args.check_for_updates:
        loom_art.banner(term)
        report_release_check(
            term,
            force=True,
            offer_open=interactive and not args.yes,
        )
        return 0

    if args.doctor:
        loom_art.banner(term)
        print(loom_ui.heading(term, "Rubric Loom doctor"))
        core_ok, _ = run_doctor(term)
        return 0 if core_ok else 2

    if template_action or args.template_destination is not None or args.replace_template:
        if args.door != "weave":
            print(
                "rubric_loom_wizard: template operations require --door weave",
                file=sys.stderr,
            )
            return 2
        if args.list_templates and (
            args.template_destination is not None or args.replace_template
        ):
            print(
                "rubric_loom_wizard: listing templates is read-only and accepts "
                "no destination or replacement flag",
                file=sys.stderr,
            )
            return 2
        if not template_action:
            print(
                "rubric_loom_wizard: --template-destination/--replace-template "
                "require --copy-template",
                file=sys.stderr,
            )
            return 2
        if args.source is not None or args.output_dir is not None or args.approve_weave:
            print(
                "rubric_loom_wizard: template delivery is separate from a Weave build",
                file=sys.stderr,
            )
            return 2

    if not template_action and args.yes and args.source is None:
        print(
            "rubric_loom_wizard: --yes needs --source PATH (defaults answer "
            "prompts; the source has no default)",
            file=sys.stderr,
        )
        return 2
    if args.door != "weave" and (
        args.approve_weave
        or args.allow_even_spacing
        or args.allow_equal_weights
        or args.context_dir is not None
        or args.source_label is not None
        or args.orgunit_identifier is not None
        or args.default_nav is not None
        or args.default_homepage is not None
        or args.title is not None
        or args.keyword is not None
        or args.manifest_identifier is not None
        or args.resource_prefix is not None
        or args.force
        or args.step_timeout != 900.0
        or args.list_templates
        or args.copy_template is not None
        or args.template_destination is not None
        or args.replace_template
    ):
        print(
            "rubric_loom_wizard: Weave-only options require --door weave",
            file=sys.stderr,
        )
        return 2
    if args.door == "weave" and args.no_docx:
        print(
            "rubric_loom_wizard: --no-docx belongs to the Unravel door",
            file=sys.stderr,
        )
        return 2
    headless = args.yes and args.source is not None
    if not template_action and not interactive and not headless:
        print(
            "rubric_loom_wizard: not a terminal; pass --source PATH --yes "
            "(and optionally --output-dir/--label/--no-docx) to run "
            "non-interactively",
            file=sys.stderr,
        )
        return 2

    try:
        if not template_action:
            if interactive and not args.brisk and not term.plain:
                loom_art.splash(term, animate=True)
            else:
                loom_art.banner(term)

        door = args.door
        if door is None:
            # Compatibility contract: every pre-R1 invocation with a source
            # remains an Unravel invocation. Only a source-less guided launch
            # opens the art-led two-door landing page.
            door = (
                choose_door(term, load_state())
                if interactive and not args.yes and args.source is None
                else "unravel"
            )
        if door == "q":
            print("  nothing was run.")
            return 0

        core_ok, docx_ok = ensure_environment(term, assume_yes=args.yes)
        if not core_ok:
            return 2
        if (
            interactive
            and not args.yes
            and not args.no_update_check
            and os.environ.get("RUBRIC_LOOM_NO_RELEASE_CHECK") is None
        ):
            report_release_check(term, force=False, offer_open=True)

        # jsonschema is now known to be available. Keep this import after the
        # repair gate so a partial environment can still reach the installer.
        import rubric_loom_weave as weave

        if template_action:
            return weave.run_template_headless(term, args)

        if door == "weave":
            saver = lambda values: save_door_state("weave", values)
            state = door_state(load_state(), "weave")
            if args.yes:
                return weave.run_headless(term, args, saver)
            return weave.run_interactive(term, args, state, saver)
        if args.yes:
            return _run_headless(term, args, docx_ok)
        return _run_interactive(term, args, docx_ok)
    except KeyboardInterrupt:
        print("\n  interrupted — nothing else was run.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
