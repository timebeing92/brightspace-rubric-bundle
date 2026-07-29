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
from dataclasses import dataclass
import importlib
import importlib.util
import json
import os
import re
import shlex
import shutil
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
USER_DATA_ROOT = Path(
    os.environ.get("RUBRIC_LOOM_USER_DATA", str(REPO_ROOT))
).expanduser().resolve()
OUTPUT_LANE = USER_DATA_ROOT / "output"
INPUT_LANE = USER_DATA_ROOT / "input"
VENV_ROOT = Path(
    os.environ.get("RUBRIC_LOOM_VENV", str(REPO_ROOT / ".venv"))
).expanduser().resolve()
LOG_NAME = "unravel_wizard.log"
RUNTIME_REQUIREMENTS = REPO_ROOT / "requirements-lock.txt"
VERSION_PATH = REPO_ROOT / "VERSION"
RELEASE_CACHE_PATH = Path(
    os.environ.get(
        "RUBRIC_LOOM_RELEASE_CACHE",
        str(OUTPUT_LANE / "update-cache" / "release_check.json"),
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
        str(OUTPUT_LANE / ".rubric_loom_wizard_state.json"),
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
EXPORT_MARKERS = ("imsmanifest.xml", unravel.RUBRIC_XML_NAME)


@dataclass(frozen=True)
class BulkDiscovery:
    """Read-only inventory of one folder selected as a batch container."""

    root: Path
    sources: tuple[Path, ...]
    ignored: tuple[Path, ...]
    problem: str = ""
    collisions: tuple[tuple[str, tuple[Path, ...]], ...] = ()


@dataclass(frozen=True)
class BulkOutcome:
    """One attempted batch item and the producer-owned result it returned."""

    source: Path
    output_dir: Path
    status: str
    return_code: int


class _UnravelMenu:
    """Navigation sentinel: return to the early Unravel choice screen."""


UNRAVEL_MENU = _UnravelMenu()


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


def navigation_footer(term: loom_ui.Term) -> None:
    print("  " + term.secondary("b = back  ·  e = exit"))


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
    """User-data-anchored default for one Unravel result."""
    return OUTPUT_LANE / f"{label}__rubric_bundle"


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
    output_lane = OUTPUT_LANE
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
        return VENV_ROOT / "Scripts" / "python.exe"
    return VENV_ROOT / "bin" / "python"


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
        "the private Rubric Loom environment"
        if running_in_local_venv()
        else str(VENV_ROOT)
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
                ("", "Nothing is installed into the system Python."),
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
            "--venv",
            str(VENV_ROOT),
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
    override = os.environ.get("RUBRIC_LOOM_INSTALLED_VERSION", "").strip()
    if override:
        return override
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
def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def _contains_export_marker(folder: Path) -> bool:
    """Whether one immediate batch child resembles an unpacked export.

    The marker must be directly inside the child. This keeps a directory that
    merely contains deeper folders from being mistaken for one course export.
    """

    return any(_regular_file(folder / marker) for marker in EXPORT_MARKERS)


def _direct_export_marker(folder: Path) -> bool:
    """A marker directly in the selected root means it is probably one export."""

    return any(_regular_file(folder / marker) for marker in EXPORT_MARKERS)


def _bulk_label_collisions(
    sources: tuple[Path, ...],
) -> tuple[tuple[str, tuple[Path, ...]], ...]:
    groups: dict[str, list[Path]] = {}
    labels: dict[str, str] = {}
    for source in sources:
        label = unravel.default_label(source)
        key = label.casefold()
        labels.setdefault(key, label)
        groups.setdefault(key, []).append(source)
    return tuple(
        (labels[key], tuple(paths))
        for key, paths in sorted(groups.items())
        if len(paths) > 1
    )


def discover_bulk_sources(root: Path) -> BulkDiscovery:
    """Inventory immediate ZIPs and immediate unpacked-export directories.

    Symlinks are never batch inputs. A root that directly carries an export
    marker is refused as an ambiguous single unpacked export. Corrupt ZIPs
    remain candidates so the pinned producer can report their real failure.
    """

    try:
        mode = root.lstat().st_mode
    except FileNotFoundError:
        return BulkDiscovery(root, (), (), "The batch folder does not exist.")
    except OSError as exc:
        return BulkDiscovery(
            root, (), (), f"The batch folder could not be inspected: {exc}"
        )
    if stat.S_ISLNK(mode):
        return BulkDiscovery(
            root, (), (), "Choose a batch folder that is not a symbolic link."
        )
    if not stat.S_ISDIR(mode):
        return BulkDiscovery(root, (), (), "The batch source must be a folder.")
    if _direct_export_marker(root):
        return BulkDiscovery(
            root,
            (),
            (),
            "This folder looks like one unpacked Brightspace export. "
            "Choose Single Unravel for this folder, or choose its parent "
            "as the Bulk Unravel source.",
        )

    sources: list[Path] = []
    ignored: list[Path] = []
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except OSError as exc:
        return BulkDiscovery(
            root, (), (), f"The batch folder could not be read: {exc}"
        )
    for child in children:
        if child.name.startswith("."):
            ignored.append(child)
            continue
        try:
            child_mode = child.lstat().st_mode
        except OSError:
            ignored.append(child)
            continue
        if stat.S_ISLNK(child_mode):
            ignored.append(child)
        elif stat.S_ISREG(child_mode) and child.suffix.lower() == ".zip":
            sources.append(child)
        elif stat.S_ISDIR(child_mode) and _contains_export_marker(child):
            sources.append(child)
        else:
            ignored.append(child)

    source_tuple = tuple(sources)
    return BulkDiscovery(
        root=root,
        sources=source_tuple,
        ignored=tuple(ignored),
        collisions=_bulk_label_collisions(source_tuple),
    )


def default_bulk_dir(root: Path) -> Path:
    label = unravel.sanitize_label(root.name or "batch")
    return OUTPUT_LANE / f"{label}__bulk_unravel"


def choose_unravel_mode(term: loom_ui.Term, *, allow_back: bool):
    print()
    return loom_ui.choose(
        term,
        "How would you like to begin?",
        [
            (
                "single",
                "ONE COURSE EXPORT — read one ZIP, unpacked export, or rubric XML",
            ),
            (
                "bulk",
                "A FOLDER OF COURSE EXPORTS — read its immediate ZIPs and export folders",
            ),
            (
                "demo",
                "THE DEMONSTRATION — try Unravel with a built-in sample export",
            ),
            ("e", "Exit without running"),
        ],
        default="single",
        allow_back=allow_back,
    )


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


def pick_source(
    term: loom_ui.Term, remembered: str
) -> Path | None | _UnravelMenu:
    print(loom_ui.paragraph(term, ACCEPTS_LINE))
    print()
    candidates = input_lane_candidates()
    remembered_path = Path(remembered) if remembered else None
    if remembered_path == FIXTURE or (
        remembered_path is not None and not remembered_path.exists()
    ):
        remembered_path = None

    if candidates:
        print(loom_ui.paragraph(term, "Ready in the input folder:", dim=True))
        for index, path in enumerate(candidates, start=1):
            print(
                f"      {term.bold(str(index))}. "
                f"{relative_display(path)}  ({source_kind(path)})"
            )
        print()

    if remembered_path is not None:
        guidance(
            term,
            f"Last used: {relative_display(remembered_path)}. "
            "Press Return to use it again.",
        )
        print()

    candidate_note = (
        f" Enter 1-{len(candidates)} to use a file already in the input folder."
        if candidates
        else ""
    )
    guidance(
        term,
        f"Drag or type a path now.{candidate_note}",
    )
    print()
    navigation_footer(term)
    print()
    while True:
        raw = loom_ui.prompt_text(
            term,
            "Course export path",
        )

        if not raw:
            if remembered_path is not None:
                return remembered_path
            print(
                term.secondary(
                    "    drag or type a path, or use b to go back"
                )
            )
            continue
        if raw.lower() in {"b", "back"}:
            return UNRAVEL_MENU
        if raw.lower() in {"e", "exit", "q", "quit"}:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(candidates):
            return candidates[int(raw) - 1]

        candidate = parse_typed_path(raw)
        if candidate is not None and candidate.exists():
            return candidate
        print(
            loom_ui.status_line(
                term,
                "bad",
                f"I could not find that file or folder: {raw}",
            )
        )


def pick_bulk_folder(
    term: loom_ui.Term, remembered: str
) -> Path | None | _UnravelMenu:
    """Prompt for a batch container; discovery validates its contents later."""

    remembered_path = Path(remembered) if remembered else None
    if remembered_path is not None and not remembered_path.is_dir():
        remembered_path = None
    guidance(
        term,
        "Choose a parent folder containing course-export ZIPs, unpacked "
        "export folders, or a mixture of both.",
    )
    print()
    if remembered_path is not None:
        guidance(
            term,
            f"Last used: {relative_display(remembered_path)}. "
            "Press Return to use it again.",
        )
        print()
    navigation_footer(term)
    print()
    while True:
        raw = loom_ui.prompt_text(
            term,
            "Folder containing the course exports",
        )
        if not raw and remembered_path is not None:
            return remembered_path
        if not raw:
            print(term.secondary("    drag or type a folder path, or use b to go back"))
            continue
        if str(raw).lower() in {"b", "back"}:
            return UNRAVEL_MENU
        if str(raw).lower() in {"e", "exit", "q", "quit"}:
            return None
        candidate = parse_typed_path(str(raw))
        if candidate is None:
            continue
        discovery = discover_bulk_sources(candidate)
        if discovery.problem:
            print(loom_ui.status_line(term, "bad", discovery.problem))
            continue
        if not discovery.sources:
            print(
                loom_ui.status_line(
                    term,
                    "bad",
                    "No course-export ZIPs or unpacked export folders were "
                    "found directly inside that folder.",
                )
            )
            continue
        return candidate


def _preview_names(paths: tuple[Path, ...], *, limit: int = 8) -> str:
    names = [path.name for path in paths[:limit]]
    if len(paths) > limit:
        names.append(f"… and {len(paths) - limit} more")
    return ", ".join(names) if names else "none"


def bulk_source_rows(discovery: BulkDiscovery) -> list[tuple[str, str]]:
    zip_count = sum(
        source.is_file() and source.suffix.lower() == ".zip"
        for source in discovery.sources
    )
    folder_count = len(discovery.sources) - zip_count
    rows = [
        ("batch folder", relative_display(discovery.root)),
        ("exports found", str(len(discovery.sources))),
        ("  ZIP files", str(zip_count)),
        ("  unpacked folders", str(folder_count)),
        ("sources", _preview_names(discovery.sources)),
        ("ignored", str(len(discovery.ignored))),
    ]
    if discovery.ignored:
        rows.append(("  not included", _preview_names(discovery.ignored, limit=5)))
    return rows


def bulk_review_rows(
    discovery: BulkDiscovery,
    output_root: Path,
    use_docx: bool,
    args,
    docx_ok: bool,
) -> list[tuple[str, str]]:
    rows = [
        ("1. Batch folder", relative_display(discovery.root)),
        ("   Exports", str(len(discovery.sources))),
        ("   Included", _preview_names(discovery.sources)),
        ("2. Save folder", relative_display(output_root)),
        ("3. Review DOCX", _review_docx_text(use_docx, args, docx_ok)),
        ("", ""),
        (
            "",
            "Each export gets its own <course>__rubric_bundle folder. "
            "Nothing is written until you press Return to start.",
        ),
    ]
    return rows


def bulk_collision_rows(
    collisions: tuple[tuple[str, tuple[Path, ...]], ...],
) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for label, paths in collisions:
        rows.append((label, ", ".join(path.name for path in paths)))
    rows += wrap_rows(
        "These source names become the same safe output name. Rename one "
        "source, then select the batch folder again."
    )
    return rows


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


def bulk_destination_problem(
    source_root: Path,
    output_root: Path,
    sources: tuple[Path, ...],
) -> str:
    """Refuse ambiguous or unsafe batch destinations before the first write."""

    source_absolute = source_root.expanduser().absolute()
    output_absolute = output_root.expanduser().absolute()
    try:
        source_compare = source_absolute.resolve()
        output_compare = output_absolute.resolve(strict=False)
    except OSError as exc:
        return f"The source and save paths could not be compared safely: {exc}"
    if output_compare == source_compare or source_compare in output_compare.parents:
        return "Choose a save folder outside the batch source folder."

    anchor, writable = output_lane_write_anchor(output_absolute)
    if not writable:
        return f"The save path is not writable at {relative_display(anchor)}."

    try:
        mode = output_absolute.lstat().st_mode
    except FileNotFoundError:
        mode = 0
    except OSError as exc:
        return f"The save folder could not be inspected: {exc}"
    if mode and stat.S_ISLNK(mode):
        return "Choose a save folder that is not a symbolic link."
    if mode and not stat.S_ISDIR(mode):
        return "The save location is an existing file, not a folder."

    for source in sources:
        label = unravel.default_label(source)
        destination = output_absolute / f"{label}__rubric_bundle"
        try:
            destination_mode = destination.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError as exc:
            return f"The course destination could not be inspected: {exc}"
        if stat.S_ISLNK(destination_mode):
            return (
                f"The planned course destination is a symbolic link: "
                f"{relative_display(destination)}"
            )
        if not stat.S_ISDIR(destination_mode):
            return (
                f"The planned course destination is an existing file: "
                f"{relative_display(destination)}"
            )
    return ""


def bulk_destination_ready(
    term: loom_ui.Term,
    source_root: Path,
    output_root: Path,
    sources: tuple[Path, ...],
) -> bool:
    problem = bulk_destination_problem(source_root, output_root, sources)
    if problem:
        print(loom_ui.status_line(term, "bad", problem))
        return False
    try:
        occupied = output_root.is_dir() and any(output_root.iterdir())
    except OSError:
        print(loom_ui.status_line(term, "bad", "The save folder could not be read."))
        return False
    if occupied:
        return bool(
            loom_ui.confirm(
                term,
                "This batch folder already contains files. Replace matching "
                "Loom files inside its course folders?",
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


def rubric_names_from_contract(path: Path) -> tuple[str, ...]:
    """Read display names from this run's normalized contract.

    The producer has already interpreted and validated the D2L source. The
    TUI reads only its delivered JSON contract and never re-parses rubric XML.
    A damaged or unexpectedly shaped file degrades to an honest missing-name
    note on the results card instead of turning a successful run into a crash.
    """

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    rubrics = document.get("rubrics") if isinstance(document, dict) else None
    if not isinstance(rubrics, list):
        return ()
    names: list[str] = []
    for rubric in rubrics:
        if not isinstance(rubric, dict):
            return ()
        name = rubric.get("name")
        names.append(
            name.strip()
            if isinstance(name, str) and name.strip()
            else "(unnamed rubric)"
        )
    return tuple(names)


def folder_open_command(path: Path) -> list[str] | None:
    if sys.platform == "darwin":
        return ["open", str(path)]
    if os.name == "nt":
        return ["explorer", str(path)]
    opener = shutil.which("xdg-open")
    return [opener, str(path)] if opener else None


def offer_open_folder(term: loom_ui.Term, path: Path) -> None:
    """Offer one explicit, post-success handoff in a live terminal."""

    if term.plain or not path.is_dir():
        return
    command = folder_open_command(path)
    if command is None:
        return
    if not loom_ui.confirm(
        term,
        "Open the folder containing these files?",
        default=True,
    ):
        return
    try:
        result = subprocess.run(command, check=False)
    except OSError:
        result = None
    if result is None or result.returncode != 0:
        print(
            loom_ui.status_line(
                term,
                "warn",
                "The folder could not be opened automatically",
                relative_display(path),
            )
        )


def run_unravel(
    term: loom_ui.Term,
    source: Path,
    out_dir: Path,
    label: str,
    use_docx: bool,
    *,
    min_step_seconds: float,
    offer_open: bool = False,
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
        if offer_open:
            offer_open_folder(term, out_dir)
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


def _bulk_status(return_code: int) -> str:
    if return_code == 0:
        return "completed"
    if return_code == 3:
        return "no rubric evidence"
    if return_code == 130:
        return "interrupted"
    return "failed"


def bulk_summary_rows(
    outcomes: tuple[BulkOutcome, ...],
    output_root: Path,
    total_sources: int,
) -> list[tuple[str, str]]:
    counts = {
        status: sum(outcome.status == status for outcome in outcomes)
        for status in ("completed", "no rubric evidence", "failed", "interrupted")
    }
    rows = [
        ("exports found", str(total_sources)),
        ("attempted", str(len(outcomes))),
        ("completed", str(counts["completed"])),
        ("no rubric evidence", str(counts["no rubric evidence"])),
        ("failed", str(counts["failed"])),
        ("interrupted", str(counts["interrupted"])),
        ("save folder", relative_display(output_root)),
    ]
    for status in ("no rubric evidence", "failed", "interrupted"):
        names = tuple(
            outcome.source for outcome in outcomes if outcome.status == status
        )
        if names:
            rows.append((f"  {status}", _preview_names(names, limit=5)))
    remaining = total_sources - len(outcomes)
    if remaining:
        rows.append(("not attempted", str(remaining)))
    return rows


def bulk_return_code(outcomes: tuple[BulkOutcome, ...]) -> int:
    if any(outcome.status == "interrupted" for outcome in outcomes):
        return 130
    if any(outcome.status == "failed" for outcome in outcomes):
        return 1
    completed = sum(outcome.status == "completed" for outcome in outcomes)
    no_evidence = sum(
        outcome.status == "no rubric evidence" for outcome in outcomes
    )
    if no_evidence and not completed:
        return 3
    if no_evidence:
        return 1
    return 0


def run_bulk_unravel(
    term: loom_ui.Term,
    args,
    source_root: Path,
    sources: tuple[Path, ...],
    output_root: Path,
    use_docx: bool,
) -> int:
    """Sequentially drive the unchanged producer once per discovered export."""

    state = door_state(load_state(), "unravel")
    state.update({"bulk_source": str(source_root), "docx": use_docx})
    save_door_state("unravel", state)
    print(loom_ui.heading(term, "The bulk unravelling", "3 of 3"))
    print(trail(term, "unravelling"))
    guidance(
        term,
        "Exports run one at a time. A failed export does not prevent the "
        "remaining exports from being checked. Ctrl-C stops before the next.",
    )

    outcomes: list[BulkOutcome] = []
    for index, source in enumerate(sources, start=1):
        label = unravel.default_label(source)
        out_dir = output_root / f"{label}__rubric_bundle"
        print()
        print(
            loom_ui.status_line(
                term,
                "ok",
                f"[{index}/{len(sources)}] {source.name}",
                f"into {relative_display(out_dir)}",
            )
        )
        try:
            return_code = run_unravel(
                term,
                source,
                out_dir,
                label,
                use_docx,
                min_step_seconds=0.0,
            )
        except OSError as exc:
            print(
                loom_ui.status_line(
                    term,
                    "bad",
                    f"{source.name} could not be run",
                    str(exc),
                )
            )
            return_code = 1
        outcome = BulkOutcome(
            source=source,
            output_dir=out_dir,
            status=_bulk_status(return_code),
            return_code=return_code,
        )
        outcomes.append(outcome)
        if return_code == 130:
            break

    frozen_outcomes = tuple(outcomes)
    print()
    print(
        loom_ui.card(
            term,
            "Bulk Unravel summary",
            bulk_summary_rows(frozen_outcomes, output_root, len(sources)),
        )
    )
    return_code = bulk_return_code(frozen_outcomes)
    if return_code == 0:
        offer_open_folder(term, output_root)
    return return_code


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
    rubric_names = rubric_names_from_contract(paths["contract JSON"])
    # A run_end of ok implies at least one rubric: the pinned extractor
    # refuses zero-rubric sources outright (its own "No <rubric> elements
    # found" failure), so no empty-success state exists to narrate.

    print()
    rows: list[tuple[str, str]] = [
        (
            "",
            loom_ui.status_line(
                term,
                "ok",
                "Unravel finished successfully — your review files are ready.",
            ).strip(),
        ),
        ("", ""),
        ("Rubrics pulled", str(rubrics)),
    ]
    for index, name in enumerate(rubric_names, start=1):
        rows.append((f"  {index}.", term.bold(name)))
    if len(rubric_names) != rubrics:
        rows.append(
            (
                "",
                term.warn(
                    "The rubric names could not be read from the delivered "
                    "JSON contract."
                ),
            )
        )
    rows.append(("Diagnostics", str(diagnostics)))
    rows.append(("", ""))
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
    print(loom_ui.card(term, term.good(VOICE_BOUND), rows))


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
        term,
        source,
        out_dir,
        label,
        use_docx,
        min_step_seconds=min_step,
        offer_open=not args.yes and not term.plain,
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


def _run_interactive(
    term: loom_ui.Term, args, docx_ok: bool
) -> int | _UnravelMenu:
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
                if picked is UNRAVEL_MENU:
                    return UNRAVEL_MENU
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


def _run_bulk_interactive(
    term: loom_ui.Term, args, docx_ok: bool
) -> int | _UnravelMenu:
    """Review one batch inventory, then drive the single-export producer."""

    if args.label is not None:
        print(
            loom_ui.status_line(
                term,
                "bad",
                "--label belongs to Single Unravel. Bulk Unravel derives one "
                "collision-checked output name from each export.",
            )
        )
        return 2

    state = door_state(load_state(), "unravel")
    source_root: Path | None = None
    discovery: BulkDiscovery | None = None
    output_root: Path | None = (
        args.output_dir.expanduser().absolute()
        if args.output_dir is not None
        else None
    )
    automatic_output = args.output_dir is None
    use_docx = (
        not args.no_docx
        and docx_ok
        and bool(state.get("docx", True))
    )
    step = "source"

    while True:
        if step == "source":
            print(loom_ui.heading(term, "The batch source", "1 of 3"))
            print(trail(term, "source"))
            print()
            guidance(
                term,
                "Choose a folder that contains several Brightspace course "
                "exports. This inventory is read-only and checks only its "
                "immediate children.",
            )
            print()
            remembered = (
                str(source_root)
                if source_root is not None
                else str(state.get("bulk_source", ""))
            )
            picked = pick_bulk_folder(term, remembered)
            if picked is UNRAVEL_MENU:
                return UNRAVEL_MENU
            if picked is None:
                print("  nothing was run.")
                return 0
            source_root = picked
            discovery = discover_bulk_sources(source_root)
            if discovery.problem:
                print(loom_ui.status_line(term, "bad", discovery.problem))
                continue
            if discovery.collisions:
                print(
                    loom_ui.card(
                        term,
                        "Bulk output names collide",
                        bulk_collision_rows(discovery.collisions),
                    )
                )
                continue
            print(
                loom_ui.card(
                    term,
                    "Bulk source check",
                    bulk_source_rows(discovery),
                )
            )
            guidance(
                term,
                "ZIPs and export-like folders are included. Everything else "
                "is listed as ignored and will not be opened by the producer.",
            )
            if output_root is None or automatic_output:
                output_root = default_bulk_dir(source_root)
            step = "review"

        elif step == "review":
            assert source_root is not None
            assert discovery is not None
            assert output_root is not None
            print(loom_ui.heading(term, "Review the batch", "2 of 3"))
            print(trail(term, "review"))
            guidance(
                term,
                "Review the inventory and destination once. Each export keeps "
                "its own producer run, log, and output folder.",
            )
            print(
                loom_ui.card(
                    term,
                    "Ready for Bulk Unravel",
                    bulk_review_rows(
                        discovery, output_root, use_docx, args, docx_ok
                    ),
                )
            )
            reply = loom_ui.review_choice(
                term,
                "Start Bulk Unravel?",
                choices=("1", "2", "3"),
                allow_back=True,
            )
            if reply == "q":
                print("  nothing was run.")
                return 0
            if reply is loom_ui.BACK or reply == "1":
                discovery = None
                step = "source"
                continue
            if reply == "2":
                changed = loom_ui.prompt_text(
                    term,
                    "Save folder for all course bundles",
                    default=str(output_root),
                    allow_back=True,
                )
                if changed is not loom_ui.BACK:
                    parsed = parse_typed_path(str(changed))
                    if parsed is not None:
                        output_root = parsed.expanduser().absolute()
                        automatic_output = False
                continue
            if reply == "3":
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
                        "Create a reviewer DOCX for each successful export?",
                        default=use_docx,
                        allow_back=True,
                    )
                    if changed is not loom_ui.BACK:
                        use_docx = bool(changed)
                continue
            if not bulk_destination_ready(
                term,
                source_root,
                output_root,
                discovery.sources,
            ):
                guidance(
                    term,
                    "Enter 2 on the review card to choose another save folder.",
                )
                continue
            return run_bulk_unravel(
                term,
                args,
                source_root,
                discovery.sources,
                output_root,
                use_docx,
            )


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
                ("UNRAVEL", "Read rubrics from one or more Brightspace exports."),
                ("  Bring", "One export, or a folder containing several exports."),
                ("  Get", "A review DOCX, editing workbook, and JSON for each course."),
                ("", ""),
                ("WEAVE", "Build a rubric-only Brightspace import package."),
                ("  Bring", "A completed Word, Markdown, or JSON rubric."),
                ("  Get", "A validated import ZIP with review and run receipts."),
                ("", ""),
                ("", "Purely deterministic software, running locally in Python."),
                ("", "No AI model reads or interprets your files."),
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
                    "UNRAVEL — read rubrics from one or more course exports",
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

        # Verify or repair the private runtime at the front door. A first-time
        # user should see setup before being asked to choose a journey or find
        # a source path.
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

        door = args.door
        unravel_mode = "single"
        if door is None:
            # Compatibility contract: every pre-R1 invocation with a source
            # remains an Unravel invocation. Only a source-less guided launch
            # opens the art-led two-door landing page.
            if interactive and not args.yes and args.source is None:
                while True:
                    door = choose_door(term, load_state())
                    if door != "unravel":
                        break
                    selected_mode = choose_unravel_mode(term, allow_back=True)
                    if selected_mode is loom_ui.BACK:
                        continue
                    if selected_mode in {"e", "q"}:
                        door = "q"
                    else:
                        unravel_mode = str(selected_mode)
                    break
            else:
                door = "unravel"
        elif (
            door == "unravel"
            and interactive
            and not args.yes
            and args.source is None
        ):
            selected_mode = choose_unravel_mode(term, allow_back=False)
            if selected_mode in {"e", "q"}:
                door = "q"
            else:
                unravel_mode = str(selected_mode)
        if door == "q":
            print("  nothing was run.")
            return 0

        if template_action:
            return weave.run_template_headless(term, args)

        if args.yes:
            if door == "weave":
                saver = lambda values: save_door_state("weave", values)
                return weave.run_headless(term, args, saver)
            return _run_headless(term, args, docx_ok)

        while True:
            if door == "weave":
                saver = lambda values: save_door_state("weave", values)
                state = door_state(load_state(), "weave")
                return weave.run_interactive(term, args, state, saver)

            if unravel_mode == "bulk":
                result = _run_bulk_interactive(term, args, docx_ok)
            elif unravel_mode == "demo":
                original_source = args.source
                args.source = FIXTURE
                try:
                    result = _run_interactive(term, args, docx_ok)
                finally:
                    args.source = original_source
            else:
                result = _run_interactive(term, args, docx_ok)

            if result is not UNRAVEL_MENU:
                return result

            while True:
                selected_mode = choose_unravel_mode(
                    term,
                    allow_back=args.door is None,
                )
                if selected_mode is not loom_ui.BACK:
                    break
                door = choose_door(term, load_state())
                if door == "q":
                    print("  nothing was run.")
                    return 0
                if door == "weave":
                    break
            if door == "weave":
                continue
            if selected_mode in {"e", "q"}:
                print("  nothing was run.")
                return 0
            door = "unravel"
            unravel_mode = str(selected_mode)
    except KeyboardInterrupt:
        print("\n  interrupted — nothing else was run.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
