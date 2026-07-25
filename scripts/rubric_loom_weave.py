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
import subprocess
import sys
from typing import Callable

import loom_progress
import loom_ui


REPO_ROOT = Path(__file__).resolve().parents[1]
ORCHESTRATOR = REPO_ROOT / "scripts" / "run_weave_bundle.py"
FIXTURE = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "rubric_authoring"
    / "three_level_explicit.md"
)
INPUT_LANE = REPO_ROOT / "input"
LOG_NAME = "weave_wizard.log"
LOG_LANE = Path(
    os.environ.get("RUBRIC_LOOM_LOG_DIR", str(REPO_ROOT / "output" / "logs"))
)
ALLOWED_SUFFIXES = {".docx", ".json", ".md", ".markdown"}
PREFLIGHT_SCHEMA = "coursecraft.rubric_authoring_preflight/1"

PHASES = ("workshop", "source", "preflight", "commission", "weaving")
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


def trail(term: loom_ui.Term, current: str) -> str:
    parts = [
        term.bold(f"[{name}]") if name == current else term.dim(name)
        for name in PHASES
    ]
    return "  " + " › ".join(parts)


def guidance(term: loom_ui.Term, text: str) -> None:
    print("  " + term.dim(text))


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
    return REPO_ROOT / "output" / f"{label}__weave_bundle"


def source_options(args, *, preflight: bool) -> list[str]:
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
    print(loom_ui.card(term, "Producer preflight", rows))


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


def pick_source(term: loom_ui.Term, remembered: str) -> Path | None:
    options: list[tuple[str, str]] = []
    candidates = input_lane_candidates()
    remembered_path = Path(remembered) if remembered else None
    default = "path"
    for index, path in enumerate(candidates, start=1):
        options.append((str(index), relative_display(path)))
        if remembered_path == path:
            default = str(index)
    options.append(("path", "type or drag a DOCX, Markdown, or JSON path"))
    options.append(("demo", f"the explicit-scoring demonstration ({relative_display(FIXTURE)})"))
    if remembered_path == FIXTURE:
        default = "demo"
    choice = loom_ui.choose(
        term,
        "Which authored rubric should the loom weave?",
        options,
        default=default,
    )
    if choice == "demo":
        return FIXTURE
    if choice == "path":
        for _ in range(3):
            raw = loom_ui.prompt_text(term, "Path to the authored rubric", default=remembered)
            candidate = parse_typed_path(raw)
            if candidate is None:
                return None
            if candidate.is_file():
                return candidate
            print(loom_ui.status_line(term, "bad", f"not found: {raw}"))
        return None
    return candidates[int(choice) - 1]


def ensure_fallback_decisions(term: loom_ui.Term, args, preflight: dict) -> tuple[bool, dict]:
    """Offer only the producer-requested fallback decisions, then re-preflight."""
    codes = diagnostic_codes(preflight)
    changed = False
    if "SCORING_METADATA_REQUIRED" in codes and not args.allow_even_spacing:
        reply = loom_ui.confirm(
            term,
            "Approve even level spacing for this run?",
            default=False,
            allow_back=True,
        )
        if reply is loom_ui.BACK or not reply:
            return False, preflight
        args.allow_even_spacing = True
        changed = True
    if "CRITERION_WEIGHT_REQUIRED" in codes and not args.allow_equal_weights:
        reply = loom_ui.confirm(
            term,
            "Approve equal criterion weights for this run?",
            default=False,
            allow_back=True,
        )
        if reply is loom_ui.BACK or not reply:
            return False, preflight
        args.allow_equal_weights = True
        changed = True
    if changed:
        _, preflight = invoke_preflight(args)
    return preflight_usable(preflight), preflight


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
    emitted = {
        item.get("path"): item
        for item in receipt.get("emitted_files", [])
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
            "woven",
            f"{int(summary.get('rubrics') or 0)} rubric(s), "
            f"{int(summary.get('diagnostics') or 0)} diagnostic(s)",
        ),
        ("start here", f"{relative_display(outputs['import_zip'])}  — Brightspace import ZIP"),
        ("normalized JSON", relative_display(outputs["normalized_authoring_json"])),
        ("mapping report", relative_display(outputs["mapping_report"])),
    ]
    if "review_report" in outputs:
        rows.append(("review report", relative_display(outputs["review_report"])))
    rows.extend(
        [
            ("diagnostics", relative_display(outputs["diagnostics_json"])),
            ("receipt", relative_display(outputs["run_identity"])),
            ("log", relative_display(log_path)),
            ("", ""),
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


def run_build(term: loom_ui.Term, args, out_dir: Path, label: str) -> int:
    command = source_options(args, preflight=False)
    command.extend(
        [
            "--output-dir",
            str(out_dir),
            "--label",
            label,
            "--progress-events",
        ]
    )
    print(loom_ui.heading(term, "The weaving", "5 of 5"))
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
    if (
        result.return_code == 0
        and result.run_end is not None
        and result.run_end.get("status") == "ok"
        and results_card(term, result.run_end, log_path)
    ):
        return 0
    if result.return_code == 0:
        result.return_code = 1
        result.failed_message = "The final receipt did not ground every required delivery claim."
    failure_card(term, result, log_path)
    return result.return_code or 1


def _commission_rows(args, source: Path, label: str, out_dir: Path) -> list[tuple[str, str]]:
    return [
        ("source", relative_display(source)),
        ("label", label),
        ("bundle", relative_display(out_dir)),
        ("even spacing", "approved" if args.allow_even_spacing else "not used"),
        ("equal weights", "approved" if args.allow_equal_weights else "not used"),
        ("Brightspace import", "not performed"),
        ("activity attachment", "manual only"),
    ]


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
    print(loom_ui.heading(term, "The source", "2 of 5"))
    print(trail(term, "source"))
    if not source.is_file():
        print(loom_ui.status_line(term, "bad", f"source not found: {source}"))
        return 2
    if source.suffix.lower() not in ALLOWED_SUFFIXES:
        print(loom_ui.status_line(term, "bad", "Weave accepts DOCX, Markdown, or JSON files"))
        return 2

    print(loom_ui.heading(term, "Producer preflight", "3 of 5"))
    print(trail(term, "preflight"))
    _, preflight = invoke_preflight(args)
    preflight_card(term, preflight)
    if not preflight_usable(preflight):
        refusal_card(term, preflight)
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
    print(loom_ui.heading(term, "The commission", "4 of 5"))
    print(trail(term, "commission"))
    print(loom_ui.card(term, "Ready to weave", _commission_rows(args, source, label, out_dir)))
    print("  ? Named final approval: WEAVE (--approve-weave)")
    save_state(
        {
            "source": str(source),
            "allow_even_spacing": bool(args.allow_even_spacing),
            "allow_equal_weights": bool(args.allow_equal_weights),
        }
    )
    return run_build(term, args, out_dir, label)


def run_interactive(
    term: loom_ui.Term,
    args,
    state: dict,
    save_state: Callable[[dict], None],
) -> int:
    source = args.source.expanduser().absolute() if args.source is not None else None
    if args.context_dir is not None:
        args.context_dir = args.context_dir.expanduser().absolute()
    print(loom_ui.heading(term, "The source", "2 of 5"))
    print(trail(term, "source"))
    guidance(term, "Choose a DOCX, Markdown, or JSON authoring source; nothing is written yet.")
    if source is None:
        source = pick_source(term, str(state.get("source", "")))
    else:
        print(loom_ui.status_line(term, "ok", f"source: {relative_display(source)}"))
    if source is None:
        print("  nothing was run.")
        return 0
    if not source.is_file() or source.suffix.lower() not in ALLOWED_SUFFIXES:
        print(loom_ui.status_line(term, "bad", "Weave accepts a readable DOCX, Markdown, or JSON file"))
        return 2
    source = source.absolute()
    args.source = source

    print(loom_ui.heading(term, "Producer preflight", "3 of 5"))
    print(trail(term, "preflight"))
    guidance(term, "Only producer-reported rubric structure and scoring evidence are shown.")
    _, preflight = invoke_preflight(args)
    preflight_card(term, preflight)
    if not preflight_usable(preflight):
        usable, preflight = ensure_fallback_decisions(term, args, preflight)
        if not usable:
            refusal_card(term, preflight)
            return 0
        print()
        print(loom_ui.card(term, "Producer preflight after explicit approvals", []))
        preflight_card(term, preflight)

    print(loom_ui.heading(term, "The commission", "4 of 5"))
    print(trail(term, "commission"))
    label = sanitize_label(args.label) if args.label else default_label(source)
    out_dir: Path | None = None
    step = "label"
    while True:
        if step == "label":
            label_reply = loom_ui.prompt_text(
                term,
                "Label for the artifacts",
                default=label,
                allow_back=True,
            )
            if label_reply is loom_ui.BACK:
                print()
                preflight_card(term, preflight)
                guidance(term, "The producer preflight is unchanged; continue or Ctrl-C to leave.")
                continue
            label = sanitize_label(str(label_reply))
            step = "folder"
        elif step == "folder":
            default_dir = out_dir or args.output_dir or default_bundle_dir(label)
            folder_reply = loom_ui.prompt_text(
                term,
                "Bundle folder",
                default=str(default_dir),
                allow_back=True,
            )
            if folder_reply is loom_ui.BACK:
                step = "label"
                continue
            out_dir = (
                parse_typed_path(str(folder_reply)) or default_dir
            ).expanduser().absolute()
            if out_dir.exists() and any(out_dir.iterdir()):
                overwrite = loom_ui.confirm(
                    term,
                    "Matching artifacts may be overwritten. Continue with this folder?",
                    default=False,
                    allow_back=True,
                )
                if overwrite is loom_ui.BACK or not overwrite:
                    continue
            step = "approval"
        else:
            assert out_dir is not None
            print(
                loom_ui.card(
                    term,
                    "Ready to weave",
                    _commission_rows(args, source, label, out_dir),
                )
            )
            guidance(term, "Type the named approval exactly; b returns to the bundle folder.")
            approval = loom_ui.prompt_text(
                term,
                "Type WEAVE to approve writing this rubric-only package",
                allow_back=True,
            )
            if approval is loom_ui.BACK:
                step = "folder"
                continue
            if str(approval).strip() != "WEAVE":
                print("  named approval was not given; nothing was run.")
                return 0
            break

    assert out_dir is not None
    save_state(
        {
            "source": str(source),
            "allow_even_spacing": bool(args.allow_even_spacing),
            "allow_equal_weights": bool(args.allow_equal_weights),
        }
    )
    return run_build(term, args, out_dir, label)
