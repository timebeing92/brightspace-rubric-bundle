#!/usr/bin/env python3
"""Bounded Weave journey for the two-door Rubric Loom terminal product.

This module is presentation and process orchestration only. It invokes
``run_weave_bundle.py`` for preflight and build, displays only fields reported
by that producer, and grounds delivery claims in the final run receipt. It
does not import rubric parsers, authoring adapters, builders, or D2L XML code.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Callable

from jsonschema import Draft7Validator

import loom_progress
import loom_ui
import rubric_loom_templates as templates


REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = REPO_ROOT / "scripts" / "run_weave_bundle.py"
FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "rubric_authoring"
    / "three_level_explicit.md"
)
USER_DATA_ROOT = Path(
    os.environ.get("RUBRIC_LOOM_USER_DATA", str(REPO_ROOT))
).expanduser().resolve()
OUTPUT_LANE = USER_DATA_ROOT / "output"
INPUT_LANE = USER_DATA_ROOT / "input"
LOG_NAME = "weave_wizard.log"
LOG_LANE = Path(
    os.environ.get("RUBRIC_LOOM_LOG_DIR", str(OUTPUT_LANE / "logs"))
)
RUN_SCHEMA_PATH = (
    REPO_ROOT / "workspace/reference/schemas/course/run_identity_schema.json"
)
ALLOWED_SUFFIXES = {".docx", ".json", ".md", ".markdown"}
PREFLIGHT_SCHEMA = "coursecraft.rubric_authoring_preflight/1"
TEMPLATE_NAMES = tuple(templates.EXPECTED_MEDIA_TYPES)

PHASES = ("source", "preflight", "review", "weaving")
VOICE_BOUND = "The cloth is bound ✦"
VOICE_SNAPPED = "A thread snapped — the scroll below tells why."
FLAVOR = {
    "Inspect source": "Finding the authored edge…",
    "Normalize authoring contract": "Setting the threads in order…",
    "Validate authoring contract": "Checking the pattern before the shuttle moves…",
    "Build rubric-only package": "Weaving the Brightspace cloth…",
    "Validate rubric package": "Testing the finished weave…",
    "Write final run receipt": "Signing the selvage…",
}


class SourceBindingError(RuntimeError):
    """The source no longer matches the exact bytes shown by preflight."""


class _TemplateHandoff:
    pass


TEMPLATE_HANDOFF = _TemplateHandoff()


def trail(term: loom_ui.Term, current: str) -> str:
    parts = [
        term.bold(f"[{name}]") if name == current else term.dim(name)
        for name in PHASES
    ]
    return "  " + " › ".join(parts)


def guidance(term: loom_ui.Term, text: str) -> None:
    print(loom_ui.paragraph(term, text, dim=True))


def relative_display(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def parse_typed_path(raw: str) -> Path | None:
    text = raw.strip()
    if not text:
        return None
    if len(text) >= 2 and (text[0] == text[-1] == "'" or text[0] == text[-1] == '"'):
        text = text[1:-1]
    elif "\\" in text:
        try:
            parts = shlex.split(text)
            if parts:
                text = parts[0] if len(parts) == 1 else " ".join(parts)
        except ValueError:
            pass
    return Path(text).expanduser()


def sanitize_label(value: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "rubric_source"


def default_label(source: Path) -> str:
    return sanitize_label(source.stem or source.name)


def default_bundle_dir(label: str) -> Path:
    return OUTPUT_LANE / f"{label}__weave_bundle"


def source_options(
    args,
    *,
    preflight: bool,
    source_binding: tuple[str, int] | None = None,
) -> list[str]:
    command = [sys.executable, str(ORCHESTRATOR), str(args.source)]
    if preflight:
        command.append("--preflight")
    for flag, enabled in (
        ("--allow-even-spacing", args.allow_even_spacing),
        ("--allow-equal-weights", args.allow_equal_weights),
        ("--force", args.force),
    ):
        if enabled:
            command.append(flag)
    for flag, value in (
        ("--context-dir", args.context_dir),
        ("--source-label", args.source_label),
        ("--orgunit-identifier", args.orgunit_identifier),
        ("--default-nav", args.default_nav),
        ("--default-homepage", args.default_homepage),
        ("--title", args.title),
        ("--keyword", args.keyword),
        ("--manifest-identifier", args.manifest_identifier),
        ("--resource-prefix", args.resource_prefix),
    ):
        if value is not None:
            command.extend([flag, str(value)])
    command.extend(["--step-timeout", str(args.step_timeout)])
    if source_binding is not None and not preflight:
        command.extend(
            [
                "--expected-source-sha256",
                source_binding[0],
                "--expected-source-bytes",
                str(source_binding[1]),
            ]
        )
    return command


def invoke_preflight(args) -> tuple[int, dict]:
    result = subprocess.run(
        source_options(args, preflight=True),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    raw = result.stdout if result.returncode == 0 else result.stderr
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = {
            "schema": PREFLIGHT_SCHEMA,
            "status": "error",
            "diagnostics": [
                {
                    "code": "PREFLIGHT_ENVELOPE_INVALID",
                    "severity": "error",
                    "message": "The pinned producer did not return a readable preflight report.",
                }
            ],
        }
    if not isinstance(value, dict):
        value = {}
    return result.returncode, value


def diagnostic_codes(preflight: dict) -> set[str]:
    return {
        str(item.get("code"))
        for item in preflight.get("diagnostics", [])
        if isinstance(item, dict) and item.get("code")
    }


def preflight_usable(preflight: dict) -> bool:
    return (
        preflight.get("schema") == PREFLIGHT_SCHEMA
        and preflight.get("status") == "ok"
        and isinstance(preflight.get("rubrics"), list)
        and bool(preflight["rubrics"])
    )


def template_completion_problem(preflight: dict) -> str | None:
    """Refuse a producer-readable source that still carries the starter title."""

    catalog, _ = templates.catalog_or_error()
    if catalog is None:
        return None
    sentinel = " ".join(catalog.completion_sentinel.split()).casefold()
    for rubric in preflight.get("rubrics", []):
        if not isinstance(rubric, dict):
            continue
        name = rubric.get("name")
        if (
            isinstance(name, str)
            and " ".join(name.split()).casefold() == sentinel
        ):
            return (
                "Producer preflight still reports the synthetic starter title. "
                "Replace the example rubric, save it, and run preflight again."
            )
    return None


def preflight_source_binding(preflight: dict) -> tuple[str, int]:
    source = preflight.get("source")
    if not isinstance(source, dict):
        raise SourceBindingError("producer preflight omitted source identity")
    digest = source.get("sha256")
    extensions = source.get("extensions")
    byte_count = extensions.get("bytes") if isinstance(extensions, dict) else None
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest.lower())
        or not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
        or byte_count < 0
    ):
        raise SourceBindingError(
            "producer preflight returned an incomplete source byte binding"
        )
    return digest.lower(), byte_count


def preflight_source_label(preflight: dict) -> str:
    source = preflight.get("source")
    label = source.get("label") if isinstance(source, dict) else None
    if not isinstance(label, str) or not label:
        raise SourceBindingError("producer preflight omitted the effective source label")
    return label


def file_source_binding(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_count += len(chunk)
    return digest.hexdigest(), byte_count


def run_end_matches_source_binding(
    run_end: dict,
    expected: tuple[str, int],
) -> bool:
    outputs = run_end.get("outputs")
    receipt_raw = outputs.get("run_identity") if isinstance(outputs, dict) else None
    if not isinstance(receipt_raw, str):
        return False
    try:
        receipt = json.loads(Path(receipt_raw).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    source = receipt.get("source") if isinstance(receipt, dict) else None
    extensions = source.get("extensions") if isinstance(source, dict) else None
    transport = (
        source.get("transport_fingerprint") if isinstance(source, dict) else None
    )
    digest = source.get("sha256") if isinstance(source, dict) else None
    byte_count = extensions.get("bytes") if isinstance(extensions, dict) else None
    if isinstance(transport, dict) and transport.get("algorithm") == "sha256":
        digest = transport.get("digest")
        byte_count = transport.get("bytes")
    return (
        isinstance(source, dict)
        and digest == expected[0]
        and byte_count == expected[1]
    )


def snapshot_source(
    source: Path,
    expected: tuple[str, int],
) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """Copy approved bytes into a private immutable locator for the build."""

    temporary = tempfile.TemporaryDirectory(prefix="rubric-loom-weave-source-")
    os.chmod(temporary.name, 0o700)
    snapshot = Path(temporary.name) / f"approved-source{source.suffix.lower()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = None
    digest = hashlib.sha256()
    byte_count = 0
    try:
        descriptor = os.open(snapshot, flags, 0o600)
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            descriptor = None
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                digest.update(chunk)
                byte_count += len(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        actual = (digest.hexdigest(), byte_count)
        if actual != expected:
            raise SourceBindingError(
                "source changed after the displayed preflight; no build was started"
            )
        os.chmod(snapshot, 0o400)
        if file_source_binding(snapshot) != expected:
            raise SourceBindingError(
                "private source snapshot failed its final integrity check"
            )
        return temporary, snapshot
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        temporary.cleanup()
        raise


def preflight_card(term: loom_ui.Term, preflight: dict) -> None:
    """Render only producer-reported authoring facts."""
    rows: list[tuple[str, str]] = []
    source = preflight.get("source")
    if isinstance(source, dict):
        rows.append(("source kind", str(source.get("media_kind") or "(reported unknown)")))
        rows.append(("adapter", str(source.get("adapter") or "(reported unknown)")))
    rows.append(("rubrics", str(preflight.get("rubric_count", 0))))
    for index, rubric in enumerate(preflight.get("rubrics", []), start=1):
        if not isinstance(rubric, dict):
            continue
        levels = [
            str(item.get("name"))
            for item in rubric.get("levels", [])
            if isinstance(item, dict) and item.get("name") is not None
        ]
        score_sources = sorted(
            {
                str(item.get("score_source"))
                for item in rubric.get("levels", [])
                if isinstance(item, dict) and item.get("score_source")
            }
        )
        weight_sources = sorted(
            {
                str(item.get("weight_source"))
                for item in rubric.get("criteria", [])
                if isinstance(item, dict) and item.get("weight_source")
            }
        )
        rows.append((f"rubric {index}", str(rubric.get("name") or "(unnamed)")))
        rows.append(("  levels", " · ".join(levels) or "(none reported)"))
        rows.append(("  scoring", ", ".join(score_sources) or "(none reported)"))
        rows.append(("  weights", ", ".join(weight_sources) or "(none reported)"))
    diagnostics = [
        item
        for item in preflight.get("diagnostics", [])
        if isinstance(item, dict)
    ]
    rows.append(("diagnostics", str(len(diagnostics))))
    for item in diagnostics:
        rows.append(
            (
                f"  {item.get('severity', 'note')}",
                f"{item.get('code', 'UNNAMED')}: {item.get('message', '')}",
            )
        )
    rows.extend(
        [
            ("", ""),
            ("", "Read-only check: no package has been written."),
        ]
    )
    print(loom_ui.card(term, "What Weave found · Producer preflight", rows))


def refusal_card(term: loom_ui.Term, preflight: dict) -> None:
    print()
    print("  " + (term.bad(VOICE_SNAPPED) if not term.plain else VOICE_SNAPPED))
    rows: list[tuple[str, str]] = []
    diagnostics = [
        item
        for item in preflight.get("diagnostics", [])
        if isinstance(item, dict)
    ]
    if diagnostics:
        for item in diagnostics:
            rows.append(
                (
                    str(item.get("code") or "PRODUCER_REFUSAL"),
                    str(item.get("message") or "The producer refused this source."),
                )
            )
            if item.get("remediation"):
                rows.append(("  next", str(item["remediation"])))
    else:
        rows.append(("", "The pinned producer refused this source."))
    rows.append(("written", "nothing"))
    print(loom_ui.card(term, "Producer preflight refused", rows))


def input_lane_candidates() -> list[Path]:
    if not INPUT_LANE.is_dir():
        return []
    try:
        return [
            child
            for child in sorted(INPUT_LANE.iterdir())
            if child.is_file()
            and not child.name.startswith(".")
            and child.suffix.lower() in ALLOWED_SUFFIXES
        ][:9]
    except OSError:
        return []


def _template_kind(asset: templates.TemplateAsset) -> str:
    return "Word" if asset.name.endswith(".docx") else "Markdown"


def _template_rows(asset: templates.TemplateAsset) -> list[tuple[str, str]]:
    return [
        ("format", f"{_template_kind(asset)} ({Path(asset.name).suffix})"),
        ("required", "A title immediately followed by its rubric table"),
        (
            "table",
            "Criterion + optional Weight + at least 2 scored level columns",
        ),
        ("multiple", "Repeat the titled table block in the same file"),
    ]


def _default_template_folder(remembered: str = "") -> Path:
    """Choose an existing, user-visible folder without creating anything."""

    remembered_folder = _existing_template_folder(remembered)
    if remembered_folder is not None:
        return remembered_folder
    for candidate in (INPUT_LANE, Path.home() / "Documents", Path.cwd()):
        try:
            mode = candidate.lstat().st_mode
        except OSError:
            continue
        if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
            return candidate
    return Path.cwd()


def _default_template_name(
    asset: templates.TemplateAsset,
    remembered: str = "",
) -> str:
    remembered_name = _template_filename(remembered, asset)
    if remembered_name is None and remembered:
        remembered_name = _template_filename(Path(remembered).stem, asset)
    return remembered_name or f"my-rubric{Path(asset.name).suffix.lower()}"


def _available_template_name(folder: Path, filename: str) -> str:
    """Suggest a non-colliding name without hiding explicit replacement."""

    def occupied(path: Path) -> bool:
        try:
            path.lstat()
        except FileNotFoundError:
            return False
        except OSError:
            return True
        return True

    if not occupied(folder / filename):
        return filename
    path = Path(filename)
    for index in range(2, 10_000):
        candidate = f"{path.stem}-{index}{path.suffix}"
        if not occupied(folder / candidate):
            return candidate
    return filename


def _template_destination_rows(
    asset: templates.TemplateAsset,
    folder: Path,
    filename: str,
) -> list[tuple[str, str]]:
    return [
        ("template", f"{_template_kind(asset)} ({Path(asset.name).suffix})"),
        ("1. save folder", relative_display(folder)),
        ("2. file name", filename),
        ("full path", relative_display(folder / filename)),
        ("", "Nothing has been copied yet."),
    ]


def _existing_template_folder(raw: str) -> Path | None:
    folder = parse_typed_path(raw)
    if folder is None:
        return None
    try:
        folder = folder.expanduser().absolute()
        mode = folder.lstat().st_mode
    except OSError:
        return None
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        return None
    return folder


def _template_filename(raw: str, asset: templates.TemplateAsset) -> str | None:
    filename = raw.strip()
    if (
        not filename
        or filename in {".", ".."}
        or "/" in filename
        or "\\" in filename
    ):
        return None
    required_suffix = Path(asset.name).suffix.lower()
    suffix = Path(filename).suffix.lower()
    if not suffix:
        filename += required_suffix
    elif suffix != required_suffix:
        return None
    return filename


def folder_open_command(path: Path) -> list[str] | None:
    if sys.platform == "darwin":
        return ["open", str(path)]
    if os.name == "nt":
        return ["explorer", str(path)]
    opener = shutil.which("xdg-open")
    return [opener, str(path)] if opener else None


def file_open_command(path: Path) -> list[str] | None:
    if sys.platform == "darwin":
        return ["open", str(path)]
    if os.name == "nt":
        return ["cmd", "/c", "start", "", str(path)]
    opener = shutil.which("xdg-open")
    return [opener, str(path)] if opener else None


def _run_open_command(
    term: loom_ui.Term,
    command: list[str] | None,
    path: Path,
    failure_message: str,
) -> bool:
    if command is None:
        print(
            loom_ui.status_line(
                term,
                "warn",
                failure_message,
                relative_display(path),
            )
        )
        return False
    try:
        result = subprocess.run(command, check=False)
    except OSError:
        result = None
    if result is not None and result.returncode == 0:
        return True
    print(
        loom_ui.status_line(
            term,
            "warn",
            failure_message,
            relative_display(path),
        )
    )
    return False


def open_template_file(term: loom_ui.Term, path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        mode = 0
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        print(
            loom_ui.status_line(
                term,
                "warn",
                "The template could not be opened automatically",
                relative_display(path),
            )
        )
        return False
    return _run_open_command(
        term,
        file_open_command(path),
        path,
        "The template could not be opened automatically",
    )


def open_template_folder(term: loom_ui.Term, path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        mode = 0
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        print(
            loom_ui.status_line(
                term,
                "warn",
                "The folder could not be opened automatically",
                relative_display(path),
            )
        )
        return False
    return _run_open_command(
        term,
        folder_open_command(path),
        path,
        "The folder could not be opened automatically",
    )


def _template_next_steps(term: loom_ui.Term, destination: Path) -> None:
    print(
        loom_ui.card(
            term,
            "Your editable template is ready",
            [
                ("saved", relative_display(destination)),
                ("next", "Replace the example and save your completed rubric."),
                ("choice", "Continue here now, or finish and return later."),
            ],
        )
    )


def _post_copy_handoff(
    term: loom_ui.Term,
    destination: Path,
    original_binding: tuple[str, int],
) -> Path | _TemplateHandoff:
    """Open the new file or folder, with an optional same-session continuation."""

    if not term.is_tty:
        return TEMPLATE_HANDOFF
    while True:
        choice = loom_ui.choose(
            term,
            "What would you like to do next?",
            [
                (
                    "continue",
                    "Open the template, edit it, then continue to Weave here",
                ),
                ("folder", "Open its folder and finish for now"),
                ("done", "Finish for now"),
            ],
            default="continue",
        )
        if choice == "done":
            return TEMPLATE_HANDOFF
        if choice == "folder":
            if open_template_folder(term, destination.parent):
                return TEMPLATE_HANDOFF
            continue
        if not open_template_file(term, destination):
            continue
        print(
            loom_ui.card(
                term,
                "Edit, save, and return",
                [
                    ("file", relative_display(destination)),
                    ("1", "Replace the synthetic example with your rubric."),
                    ("2", "Save the file in Word or your Markdown editor."),
                    ("3", "Return here and press Return to continue."),
                ],
            )
        )
        while True:
            reply = loom_ui.prompt_text(
                term,
                "Continue with the saved rubric? (q = finish for now)",
                allow_back=True,
            )
            if reply is loom_ui.BACK:
                break
            if str(reply).strip().lower() in {"q", "quit"}:
                return TEMPLATE_HANDOFF
            try:
                mode = destination.lstat().st_mode
                current_binding = file_source_binding(destination)
            except OSError:
                mode = 0
                current_binding = original_binding
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                print(
                    loom_ui.status_line(
                        term,
                        "bad",
                        "The saved template is no longer a readable regular file",
                    )
                )
                continue
            if current_binding == original_binding:
                print(
                    loom_ui.status_line(
                        term,
                        "warn",
                        "The template has not changed yet",
                        "Save your edits, then press Return again.",
                    )
                )
                continue
            print(
                loom_ui.status_line(
                    term,
                    "ok",
                    "saved edits detected; continuing to Weave preflight",
                    relative_display(destination),
                )
            )
            return destination


def _interactive_template_handoff(
    term: loom_ui.Term,
    *,
    remembered_folder: str = "",
    remembered_filename: str = "",
    remember_destination: Callable[[dict[str, str]], None] | None = None,
) -> Path | _TemplateHandoff | None:
    catalog, error = templates.catalog_or_error()
    if catalog is None:
        print(
            loom_ui.status_line(
                term,
                "warn",
                "editable templates are unavailable",
                error or "integrity check failed",
            )
        )
        return None
    print(
        loom_ui.card(
            term,
            "Create a new rubric from a template",
            [
                (
                    "",
                    "Choose Word or Markdown. Rubric Loom will make an editable "
                    "copy using the folder and file name you choose.",
                ),
            ],
        )
    )
    options = [
        (
            asset.name,
            (
                "Word document (.docx) — easiest for most people"
                if asset.name.endswith(".docx")
                else "Markdown file (.md) — for plain-text editing"
            ),
        )
        for asset in catalog.assets
    ]
    options.append(("back", "Return to source selection"))
    choice = loom_ui.choose(
        term,
        "Which type of editable template would you like?",
        options,
        default=catalog.assets[0].name,
        allow_back=True,
    )
    if choice is loom_ui.BACK or choice == "back":
        return None
    asset = next(item for item in catalog.assets if item.name == choice)
    print(loom_ui.card(term, "About this template", _template_rows(asset)))
    folder = _default_template_folder(remembered_folder)
    base_filename = _default_template_name(asset, remembered_filename)
    filename = _available_template_name(
        folder,
        base_filename,
    )
    filename_edited = False
    while True:
        guidance(
            term,
            "Press Return to save, or change the numbered folder or file name.",
        )
        print(
            loom_ui.card(
                term,
                "Where should the editable copy go?",
                _template_destination_rows(asset, folder, filename),
            )
        )
        reply = loom_ui.review_choice(
            term,
            "Save this editable template?",
            choices=("1", "2"),
            allow_back=True,
            allow_quit=False,
        )
        if reply is loom_ui.BACK:
            return None
        if reply == "1":
            print()
            guidance(term, "Tip: drag a folder into this window to paste its path.")
            print()
            raw_folder = loom_ui.prompt_text(
                term,
                "Folder for the editable copy",
                default=str(folder),
                allow_back=True,
            )
            if raw_folder is loom_ui.BACK:
                continue
            chosen_folder = _existing_template_folder(str(raw_folder))
            if chosen_folder is None:
                print(
                    loom_ui.status_line(
                        term,
                        "bad",
                        "Choose an existing folder (not a file or shortcut)",
                    )
                )
                continue
            folder = chosen_folder
            filename = _available_template_name(
                folder,
                filename if filename_edited else base_filename,
            )
            continue
        if reply == "2":
            raw_name = loom_ui.prompt_text(
                term,
                "File name",
                default=filename,
                allow_back=True,
            )
            if raw_name is loom_ui.BACK:
                continue
            chosen_name = _template_filename(str(raw_name), asset)
            if chosen_name is None:
                print(
                    loom_ui.status_line(
                        term,
                        "bad",
                        f"Use a file name ending in {Path(asset.name).suffix}",
                    )
                )
                continue
            filename = chosen_name
            filename_edited = True
            continue

        destination = (folder / filename).absolute()
        replace = False
        try:
            destination_stat = destination.lstat()
        except FileNotFoundError:
            destination_stat = None
        except OSError as exc:
            print(loom_ui.status_line(term, "bad", f"destination unavailable: {exc}"))
            continue
        if destination_stat is not None:
            if stat.S_ISLNK(destination_stat.st_mode):
                print(
                    loom_ui.status_line(
                        term, "bad", "refusing a symlink destination"
                    )
                )
                continue
            if not stat.S_ISREG(destination_stat.st_mode):
                print(
                    loom_ui.status_line(
                        term, "bad", "refusing a non-regular destination"
                    )
                )
                continue
            replace_reply = loom_ui.confirm(
                term,
                "Replace this existing file with a fresh template?",
                default=False,
                allow_back=True,
            )
            if replace_reply is loom_ui.BACK or not replace_reply:
                continue
            replace = True
        try:
            copied_asset, copied_path = templates.copy_template(
                asset.name,
                destination,
                replace=replace,
            )
        except (templates.TemplateCopyError, templates.TemplateIntegrityError) as exc:
            print(loom_ui.status_line(term, "bad", str(exc)))
            continue
        print(
            loom_ui.status_line(
                term,
                "ok",
                f"saved {_template_kind(copied_asset)} template",
                relative_display(copied_path),
            )
        )
        _template_next_steps(term, copied_path)
        if remember_destination is not None:
            remember_destination(
                {
                    "template_folder": str(copied_path.parent),
                    "template_filename": copied_path.name,
                }
            )
        return _post_copy_handoff(
            term,
            copied_path,
            (copied_asset.sha256, copied_asset.bytes),
        )


def run_template_headless(term: loom_ui.Term, args) -> int:
    """List or explicitly copy release-pinned templates without a rubric build."""

    catalog, error = templates.catalog_or_error()
    if catalog is None:
        print(
            json.dumps(
                {
                    "schema": templates.CATALOG_SCHEMA,
                    "status": "unavailable",
                    "error": error or "template integrity check failed",
                    "written": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    if args.list_templates:
        print(json.dumps(catalog.release_record(), indent=2, sort_keys=True))
        return 0
    if args.template_destination is None:
        print(
            "rubric_loom_wizard: --copy-template requires "
            "--template-destination PATH",
            file=sys.stderr,
        )
        return 2
    try:
        asset, destination = templates.copy_template(
            args.copy_template,
            args.template_destination,
            replace=args.replace_template,
        )
    except (templates.TemplateCopyError, templates.TemplateIntegrityError) as exc:
        print(f"rubric_loom_wizard: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "schema": templates.CATALOG_SCHEMA,
                "status": "copied",
                "template": asset.release_record(),
                "destination": str(destination),
                "written": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(
        "Complete and save the copy, return to Weave and select it, run producer "
        "preflight, correct or explicitly approve only a permitted fallback, "
        "then give the named WEAVE approval for a validated rubric-only package. "
        "Nothing was imported; attachment remains manual; scoring is never "
        "silently invented."
    )
    return 0


def pick_source(
    term: loom_ui.Term,
    remembered: str,
    *,
    template_folder: str = "",
    template_filename: str = "",
    remember_destination: Callable[[dict[str, str]], None] | None = None,
) -> Path | None | _TemplateHandoff:
    """Choose a source with constant-stack navigation between source screens."""

    while True:
        options: list[tuple[str, str]] = []
        catalog, template_error = templates.catalog_or_error()
        if catalog is not None:
            options.append(
                (
                    "template",
                    "Create a new rubric from an editable Word or Markdown template",
                )
            )
        else:
            print(
                loom_ui.status_line(
                    term,
                    "warn",
                    "template convenience is unavailable; ordinary Weave remains available",
                    template_error or "integrity check failed",
                )
            )
        candidates = input_lane_candidates()
        remembered_path = Path(remembered) if remembered else None
        default = "path"
        for index, path in enumerate(candidates, start=1):
            options.append((str(index), relative_display(path)))
            if remembered_path == path:
                default = str(index)
        options.append(
            (
                "path",
                "Enter or drag a completed Word, Markdown, or JSON rubric",
            )
        )
        options.append(
            (
                "demo",
                f"Try the built-in demonstration  ({relative_display(FIXTURE)})",
            )
        )
        options.append(("q", "Leave without running"))
        if remembered_path == FIXTURE:
            default = "demo"
        choice = loom_ui.choose(
            term,
            "How would you like to begin?",
            options,
            default=default,
            allow_back=True,
        )
        if choice is loom_ui.BACK or choice == "q":
            return None
        if choice == "template":
            handoff = _interactive_template_handoff(
                term,
                remembered_folder=template_folder,
                remembered_filename=template_filename,
                remember_destination=remember_destination,
            )
            if handoff is not None:
                return handoff
            continue
        if choice == "demo":
            return FIXTURE
        if choice == "path":
            while True:
                print()
                guidance(
                    term,
                    "Tip: drag the file into this window to paste its full path.",
                )
                print()
                raw = loom_ui.prompt_text(
                    term,
                    "Completed rubric path",
                    default=remembered,
                    allow_back=True,
                )
                if raw is loom_ui.BACK:
                    break
                candidate = parse_typed_path(str(raw))
                if candidate is None:
                    return None
                if candidate.is_file():
                    return candidate
                print(
                    loom_ui.status_line(
                        term, "bad", f"I could not find that file: {raw}"
                    )
                )
        return candidates[int(choice) - 1]


def ensure_fallback_decisions(
    term: loom_ui.Term,
    args,
    preflight: dict,
) -> tuple[str, dict]:
    """Navigate producer-requested fallbacks, preserving Back as navigation."""

    codes = diagnostic_codes(preflight)
    initial_even = bool(args.allow_even_spacing)
    initial_equal = bool(args.allow_equal_weights)
    decisions: list[tuple[str, str]] = []
    if "SCORING_METADATA_REQUIRED" in codes and not initial_even:
        decisions.append(
            (
                "allow_even_spacing",
                "The source does not provide complete level scores. Use evenly "
                "spaced scores across its levels for this run?",
            )
        )
    if "CRITERION_WEIGHT_REQUIRED" in codes and not initial_equal:
        decisions.append(
            (
                "allow_equal_weights",
                "The source does not provide complete criterion weights. Give "
                "each criterion equal weight for this run?",
            )
        )
    index = 0
    while index < len(decisions):
        attribute, prompt = decisions[index]
        reply = loom_ui.confirm(
            term,
            prompt,
            default=False,
            allow_back=True,
        )
        if reply is loom_ui.BACK:
            setattr(args, attribute, False)
            if index == 0:
                args.allow_even_spacing = initial_even
                args.allow_equal_weights = initial_equal
                return "back", preflight
            index -= 1
            previous_attribute, _ = decisions[index]
            setattr(args, previous_attribute, False)
            continue
        if not reply:
            args.allow_even_spacing = initial_even
            args.allow_equal_weights = initial_equal
            return "refused", preflight
        setattr(args, attribute, True)
        index += 1
    if decisions:
        _, preflight = invoke_preflight(args)
    return ("usable" if preflight_usable(preflight) else "refused"), preflight


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt_matches_run_schema(receipt: object) -> bool:
    """Validate a final receipt against the pinned coursecraft.run/1 schema."""

    if not isinstance(receipt, dict):
        return False
    try:
        schema = json.loads(RUN_SCHEMA_PATH.read_text(encoding="utf-8"))
        if (
            not isinstance(schema, dict)
            or schema.get("$id") != "coursecraft.run/1"
        ):
            return False
        Draft7Validator.check_schema(schema)
        return not any(Draft7Validator(schema).iter_errors(receipt))
    except Exception:
        # This is a delivery-claim boundary: unreadable or invalid validation
        # infrastructure must suppress claims instead of escaping as a crash.
        return False


def grounded_outputs(run_end: dict) -> dict[str, Path]:
    """Return only outputs whose current bytes are named by the final receipt."""
    outputs = run_end.get("outputs")
    if not isinstance(outputs, dict):
        return {}
    receipt_raw = outputs.get("run_identity")
    if not isinstance(receipt_raw, str):
        return {}
    receipt_path = Path(receipt_raw).resolve()
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not receipt_matches_run_schema(receipt):
        return {}
    if (
        receipt.get("schema") != "coursecraft.run/1"
        or receipt.get("status") != "ok"
        or (
            receipt.get("extensions", {}).get("activity_attachment")
            if isinstance(receipt.get("extensions"), dict)
            else None
        )
        != "manual_only"
    ):
        return {}
    bundle_raw = run_end.get("bundle_dir")
    if not isinstance(bundle_raw, str):
        return {}
    bundle = Path(bundle_raw).resolve()
    if receipt_path.parent != bundle or receipt.get("receipt_path") != receipt_path.name:
        return {}
    emitted_files = receipt.get("emitted_files")
    if not isinstance(emitted_files, list):
        return {}
    emitted = {
        item.get("path"): item
        for item in emitted_files
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    expected_roles = {
        "import_zip": "rubric_import_package",
        "rubrics_xml": "rubrics_xml_companion",
        "normalized_authoring_json": "normalized_authoring_contract",
        "mapping_report": "mapping_review",
        "review_report": "docx_conversion_review",
        "diagnostics_json": "diagnostics",
    }
    grounded: dict[str, Path] = {"run_identity": receipt_path}
    for key, raw in outputs.items():
        if key == "run_identity" or raw is None or not isinstance(raw, str):
            continue
        path = Path(raw).resolve()
        try:
            relative = path.relative_to(bundle).as_posix()
        except ValueError:
            continue
        claim = emitted.get(relative)
        extensions = claim.get("extensions") if isinstance(claim, dict) else None
        if (
            path.is_file()
            and isinstance(claim, dict)
            and isinstance(extensions, dict)
            and extensions.get("role") == expected_roles.get(key)
            and path.stat().st_size == claim.get("bytes")
            and sha256_file(path) == claim.get("sha256")
        ):
            grounded[key] = path
    return grounded


def results_card(term: loom_ui.Term, run_end: dict, log_path: Path) -> bool:
    outputs = grounded_outputs(run_end)
    required = {
        "import_zip",
        "normalized_authoring_json",
        "mapping_report",
        "diagnostics_json",
        "run_identity",
    }
    if not required <= outputs.keys():
        return False
    summary = run_end.get("summary") if isinstance(run_end.get("summary"), dict) else {}
    rows: list[tuple[str, str]] = [
        (
            "Built",
            f"{int(summary.get('rubrics') or 0)} rubric(s), "
            f"{int(summary.get('diagnostics') or 0)} diagnostic(s)",
        ),
        (
            "start here",
            f"{relative_display(outputs['import_zip'])}  — Brightspace import ZIP",
        ),
        (
            "Normalized rubric",
            relative_display(outputs["normalized_authoring_json"]),
        ),
        ("Mapping review", relative_display(outputs["mapping_report"])),
    ]
    if "review_report" in outputs:
        rows.append(("DOCX review", relative_display(outputs["review_report"])))
    rows.extend(
        [
            ("Diagnostics", relative_display(outputs["diagnostics_json"])),
            ("Run receipt", relative_display(outputs["run_identity"])),
            ("Run log", relative_display(log_path)),
            ("", ""),
            (
                "",
                "Next: review the mapping and diagnostics, then import the ZIP "
                "yourself in Brightspace.",
            ),
            ("", "Nothing was imported. Activity attachment remains manual."),
        ]
    )
    print()
    print(loom_ui.card(term, VOICE_BOUND, rows))
    return True


def failure_card(term: loom_ui.Term, result: loom_progress.ProgressRun, log_path: Path) -> None:
    print()
    print("  " + (term.bad(VOICE_SNAPPED) if not term.plain else VOICE_SNAPPED))
    message = result.failed_message
    if result.run_end and result.run_end.get("message"):
        message = message or str(result.run_end["message"])
    rows = [
        ("failed step", result.failed_step or "(before the first step)"),
        ("reason", message or f"the orchestrator exited {result.return_code}"),
        ("delivery", "no artifact is claimed from an incomplete Weave run"),
        ("log", relative_display(log_path)),
    ]
    print(loom_ui.card(term, "the scroll", rows))


def run_build(
    term: loom_ui.Term,
    args,
    out_dir: Path,
    label: str,
    source_binding: tuple[str, int],
) -> int:
    command = source_options(
        args,
        preflight=False,
        source_binding=source_binding,
    )
    command.extend(
        [
            "--output-dir",
            str(out_dir),
            "--label",
            label,
            "--progress-events",
        ]
    )
    print(loom_ui.heading(term, "The weaving", "4 of 4"))
    print(trail(term, "weaving"))
    guidance(term, "The board is live — real producer steps and timings. Ctrl-C stops cleanly.")
    # The pinned producer requires a clean output destination. Keep the log
    # in the Loom's controlled log lane—not beside an arbitrary operator
    # target—and create it exclusively without following symlinks.
    log_path = LOG_LANE / f"{label}__{secrets.token_hex(6)}__{LOG_NAME}"
    result = loom_progress.consume(
        term,
        command,
        log_path,
        log_title="rubric_loom_wizard weave run",
        flavor=FLAVOR,
        min_step_seconds=0.0 if (args.brisk or term.plain) else 1.1,
        exclusive_log=True,
    )
    if result.interrupted:
        print()
        print(
            loom_ui.card(
                term,
                "The shuttle rests — interrupted",
                [
                    ("completed", ", ".join(result.ok_steps) or "no step had finished"),
                    ("delivery", "no artifact is claimed from an interrupted Weave run"),
                    ("log", relative_display(log_path)),
                ],
            )
        )
        return 130
    binding_ok = False
    if result.run_end is not None:
        try:
            binding_ok = (
                file_source_binding(args.source) == source_binding
                and run_end_matches_source_binding(result.run_end, source_binding)
            )
        except OSError:
            binding_ok = False
    if (
        result.return_code == 0
        and result.run_end is not None
        and result.run_end.get("status") == "ok"
        and binding_ok
        and results_card(term, result.run_end, log_path)
    ):
        return 0
    if result.return_code == 0:
        result.return_code = 1
        result.failed_message = (
            "The final receipt did not ground every required delivery claim "
            "and the exact source bytes approved at preflight."
        )
    failure_card(term, result, log_path)
    return result.return_code or 1


def run_build_from_approved_snapshot(
    term: loom_ui.Term,
    args,
    original_source: Path,
    out_dir: Path,
    label: str,
    source_binding: tuple[str, int],
    approved_source_label: str,
) -> int:
    temporary, snapshot = snapshot_source(original_source, source_binding)
    previous_source = args.source
    previous_source_label = args.source_label
    try:
        args.source = snapshot
        args.source_label = approved_source_label
        return run_build(term, args, out_dir, label, source_binding)
    finally:
        args.source = previous_source
        args.source_label = previous_source_label
        temporary.cleanup()


def _commission_rows(args, source: Path, label: str, out_dir: Path) -> list[tuple[str, str]]:
    return [
        ("1. Source", relative_display(source)),
        ("2. Output name", label),
        ("3. Save folder", relative_display(out_dir)),
        ("   Import ZIP", "rubric_package.zip"),
        (
            "Scoring",
            "even spacing approved"
            if args.allow_even_spacing
            else "source scoring preserved",
        ),
        (
            "Weights",
            "equal weights approved"
            if args.allow_equal_weights
            else "source weights preserved",
        ),
        ("", ""),
        ("", "Nothing is written until the final WEAVE approval."),
        ("", "Import and activity attachment remain manual in Brightspace."),
    ]


def output_destination_problem(out_dir: Path) -> str | None:
    try:
        mode = out_dir.lstat().st_mode
    except FileNotFoundError:
        return None
    except OSError:
        return "the save folder could not be inspected"
    if stat.S_ISLNK(mode):
        return "choose a save folder that is not a symbolic link"
    if not stat.S_ISDIR(mode):
        return "the save location is an existing file, not a folder"
    return None


def source_output_separation_problem(source: Path, out_dir: Path) -> str | None:
    """Keep the original source protected while the producer reads a snapshot."""

    try:
        resolved_source = source.expanduser().resolve()
        resolved_output = out_dir.expanduser().resolve(strict=False)
    except OSError:
        return "the source or save folder could not be resolved safely"
    if (
        resolved_source == resolved_output
        or resolved_source.is_relative_to(resolved_output)
    ):
        return "the save folder must not contain the original source"
    return None


def run_headless(
    term: loom_ui.Term,
    args,
    save_state: Callable[[dict], None],
) -> int:
    # Make paths independent of the orchestrator's repo-root cwd without
    # resolving symlinks. The pinned producer must see symlink components so
    # its replacement-target safety checks cannot be bypassed by the TUI.
    source = args.source.expanduser().absolute()
    if args.context_dir is not None:
        args.context_dir = args.context_dir.expanduser().absolute()
    args.source = source
    print(loom_ui.heading(term, "The source", "1 of 4"))
    print(trail(term, "source"))
    if not source.is_file():
        print(loom_ui.status_line(term, "bad", f"source not found: {source}"))
        return 2
    if source.suffix.lower() not in ALLOWED_SUFFIXES:
        print(loom_ui.status_line(term, "bad", "Weave accepts DOCX, Markdown, or JSON files"))
        return 2

    print(loom_ui.heading(term, "Check the rubric · producer preflight", "2 of 4"))
    print(trail(term, "preflight"))
    _, preflight = invoke_preflight(args)
    preflight_card(term, preflight)
    if not preflight_usable(preflight):
        refusal_card(term, preflight)
        return 2
    completion_problem = template_completion_problem(preflight)
    if completion_problem:
        print(
            loom_ui.status_line(
                term,
                "bad",
                "Starter template is not complete",
                completion_problem,
            )
        )
        return 2
    try:
        source_binding = preflight_source_binding(preflight)
        approved_source_label = preflight_source_label(preflight)
    except SourceBindingError as exc:
        print(loom_ui.status_line(term, "bad", str(exc)))
        return 2
    if not args.approve_weave:
        print(
            "rubric_loom_wizard: headless Weave requires --approve-weave; "
            "preflight wrote nothing",
            file=sys.stderr,
        )
        return 2

    label = sanitize_label(args.label) if args.label else default_label(source)
    out_dir = (args.output_dir or default_bundle_dir(label)).expanduser().absolute()
    destination_problem = output_destination_problem(out_dir)
    destination_problem = destination_problem or source_output_separation_problem(
        source, out_dir
    )
    if destination_problem:
        print(loom_ui.status_line(term, "bad", destination_problem))
        return 2
    print(loom_ui.heading(term, "Review and build", "3 of 4"))
    print(trail(term, "review"))
    print(loom_ui.card(term, "Ready to weave", _commission_rows(args, source, label, out_dir)))
    print("  ? Named final approval: WEAVE (--approve-weave)")
    save_state(
        {
            "source": str(source),
            "allow_even_spacing": bool(args.allow_even_spacing),
            "allow_equal_weights": bool(args.allow_equal_weights),
        }
    )
    try:
        return run_build_from_approved_snapshot(
            term,
            args,
            source,
            out_dir,
            label,
            source_binding,
            approved_source_label,
        )
    except SourceBindingError as exc:
        print(loom_ui.status_line(term, "bad", str(exc)))
        print("  source review is stale; run preflight again before building.")
        return 2


def run_interactive(
    term: loom_ui.Term,
    args,
    state: dict,
    save_state: Callable[[dict], None],
) -> int:
    provided_source = (
        args.source.expanduser().absolute() if args.source is not None else None
    )
    source = provided_source
    label: str | None = sanitize_label(args.label) if args.label else None
    out_dir: Path | None = (
        args.output_dir.expanduser().absolute()
        if args.output_dir is not None
        else None
    )
    automatic_label = args.label is None
    automatic_folder = args.output_dir is None
    explicit_even_spacing = bool(args.allow_even_spacing)
    explicit_equal_weights = bool(args.allow_equal_weights)
    if args.context_dir is not None:
        args.context_dir = args.context_dir.expanduser().absolute()

    def remember(values: dict[str, object]) -> None:
        state.update(values)
        save_state(dict(state))

    def remembered_text(key: str) -> str:
        value = state.get(key)
        return value if isinstance(value, str) else ""

    while True:
        args.allow_even_spacing = explicit_even_spacing
        args.allow_equal_weights = explicit_equal_weights
        print(loom_ui.heading(term, "The source", "1 of 4"))
        print(trail(term, "source"))
        print()
        guidance(
            term,
            "Choose a completed rubric file, or create an editable starter "
            "template. Nothing is packaged until you approve a completed source.",
        )
        print()
        if source is None:
            picked = pick_source(
                term,
                remembered_text("source"),
                template_folder=remembered_text("template_folder"),
                template_filename=remembered_text("template_filename"),
                remember_destination=remember,
            )
            if picked is TEMPLATE_HANDOFF:
                print(
                    "  Your template is ready; no package was built. Its folder "
                    "will be remembered when you return to Weave."
                )
                return 0
            source = picked
        else:
            print(
                loom_ui.status_line(
                    term, "ok", f"source: {relative_display(source)}"
                )
            )
        if source is None:
            print("  nothing was run.")
            return 0
        if not source.is_file() or source.suffix.lower() not in ALLOWED_SUFFIXES:
            print(
                loom_ui.status_line(
                    term,
                    "bad",
                    "Weave accepts a readable DOCX, Markdown, or JSON file",
                )
            )
            return 2
        source = source.absolute()
        args.source = source
        if label is None or automatic_label:
            label = default_label(source)
        if out_dir is None or automatic_folder:
            out_dir = default_bundle_dir(label).expanduser().absolute()

        print(
            loom_ui.heading(
                term, "Check the rubric · producer preflight", "2 of 4"
            )
        )
        print(trail(term, "preflight"))
        guidance(
            term,
            "Weave checks the rubric structure, scoring evidence, and weights "
            "before it offers to build anything.",
        )
        _, preflight = invoke_preflight(args)
        preflight_card(term, preflight)
        if not preflight_usable(preflight):
            fallback_status, preflight = ensure_fallback_decisions(
                term, args, preflight
            )
            if fallback_status == "back":
                if provided_source is None:
                    source = None
                continue
            if fallback_status != "usable":
                refusal_card(term, preflight)
                return 0
            print()
            print(
                loom_ui.card(
                    term, "Preflight after your explicit scoring decisions", []
                )
            )
            preflight_card(term, preflight)
        completion_problem = template_completion_problem(preflight)
        if completion_problem:
            print(
                loom_ui.status_line(
                    term,
                    "bad",
                    "Starter template is not complete",
                    completion_problem,
                )
            )
            if provided_source is None:
                source = None
                continue
            return 0
        try:
            source_binding = preflight_source_binding(preflight)
            approved_source_label = preflight_source_label(preflight)
        except SourceBindingError as exc:
            print(loom_ui.status_line(term, "bad", str(exc)))
            return 2

        print(loom_ui.heading(term, "Review and build", "3 of 4"))
        print(trail(term, "review"))
        restart_preflight = False
        while True:
            assert label is not None
            assert out_dir is not None
            guidance(
                term,
                "Recommended names are ready. Press Return to continue to the "
                "final approval, or change one numbered item.",
            )
            print(
                loom_ui.card(
                    term,
                    "Ready to weave",
                    _commission_rows(args, source, label, out_dir),
                )
            )
            reply = loom_ui.review_choice(
                term,
                "Continue to final approval?",
                choices=("1", "2", "3"),
                allow_back=True,
            )
            if reply == "q":
                print("  nothing was run.")
                return 0
            if reply is loom_ui.BACK or reply == "1":
                if provided_source is None:
                    source = None
                restart_preflight = True
                break
            if reply == "2":
                label_reply = loom_ui.prompt_text(
                    term,
                    "Output name (used in the run record and default folder)",
                    default=label,
                    allow_back=True,
                )
                if label_reply is loom_ui.BACK:
                    continue
                label = sanitize_label(str(label_reply))
                automatic_label = False
                if automatic_folder:
                    out_dir = default_bundle_dir(label).expanduser().absolute()
                continue
            if reply == "3":
                folder_reply = loom_ui.prompt_text(
                    term,
                    "Save folder",
                    default=str(out_dir),
                    allow_back=True,
                )
                if folder_reply is loom_ui.BACK:
                    continue
                parsed = parse_typed_path(str(folder_reply))
                if parsed is not None:
                    out_dir = parsed.expanduser().absolute()
                    automatic_folder = False
                continue

            destination_problem = output_destination_problem(out_dir)
            destination_problem = (
                destination_problem
                or source_output_separation_problem(source, out_dir)
            )
            if destination_problem:
                print(loom_ui.status_line(term, "bad", destination_problem))
                guidance(term, "Enter 3 on the review card to choose another folder.")
                continue
            if out_dir.exists() and any(out_dir.iterdir()):
                overwrite = loom_ui.confirm(
                    term,
                    "This folder already contains files. Replace matching Loom files?",
                    default=False,
                    allow_back=True,
                )
                if overwrite is loom_ui.BACK or not overwrite:
                    guidance(
                        term,
                        "Enter 3 on the review card to choose another folder.",
                    )
                    continue

            guidance(
                term,
                "This approval writes the package shown above. Type it exactly; "
                "b returns to the review card.",
            )
            approval = loom_ui.prompt_text(
                term,
                "Type WEAVE to build this rubric-only package",
                allow_back=True,
            )
            if approval is loom_ui.BACK:
                continue
            if str(approval).strip() != "WEAVE":
                print("  WEAVE was not entered; nothing was written.")
                return 0
            break

        if restart_preflight:
            continue

        assert label is not None
        assert out_dir is not None
        remember(
            {
                "source": str(source),
                "allow_even_spacing": bool(args.allow_even_spacing),
                "allow_equal_weights": bool(args.allow_equal_weights),
            }
        )
        try:
            return run_build_from_approved_snapshot(
                term,
                args,
                source,
                out_dir,
                label,
                source_binding,
                approved_source_label,
            )
        except SourceBindingError as exc:
            print(
                loom_ui.status_line(
                    term,
                    "warn",
                    str(exc),
                )
            )
            guidance(
                term,
                "The source review is stale. Weave is restarting preflight; "
                "fallback approvals and named approval must be made again.",
            )
