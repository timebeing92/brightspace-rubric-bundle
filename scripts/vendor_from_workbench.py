#!/usr/bin/env python3
"""Promote and verify the byte-pinned Rubric Loom surface from Workbench."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = REPO_ROOT / "upstream" / "workbench_pin.json"
PIN_SCHEMA = "coursecraft.workbench_vendor_pin/1"
SOURCE_REMOTE = "https://github.com/timebeing92/coursecraft-workbench.git"
ACCEPTED_PRODUCER_COMMIT = "7c5140545548c89a254ac4502cfdd7ee6fb44255"

SOURCE_FILES = (
    "scripts/build_rubric_package.py",
    "scripts/common_xml.py",
    "scripts/extract_course_context.py",
    "scripts/extract_rubrics_to_workbook.py",
    "scripts/flat_markdown_to_json.py",
    "scripts/generate_rubric_weave_intake_templates.py",
    "scripts/make_rubric_package.py",
    "scripts/rubric_authoring.py",
    "scripts/rubric_package_lib.py",
    "scripts/rubrics_to_docx.py",
    "scripts/validate_rubric_package.py",
    "tests/test_extract_rubrics_to_workbook.py",
    "tests/test_rubric_authoring.py",
    "tests/test_rubric_package_builder.py",
    "tests/test_rubric_weave_templates.py",
    "workspace/reference/schemas/course/run_identity_schema.json",
    "workspace/reference/schemas/rubrics/rubric_authoring_schema.json",
)

SOURCE_TREES = (
    "tests/fixtures/rubric_package",
    "tests/fixtures/rubric_authoring",
    "tests/fixtures/tiny_rubrics_export",
    "workspace/reference/schemas/rubrics",
    "workspace/reference/templates/rubric-weave/v1",
)

RENAMED_SOURCES: dict[str, str] = {}
TEMPLATE_ONLY_SOURCES = {
    "scripts/generate_rubric_weave_intake_templates.py",
    "tests/test_rubric_weave_templates.py",
}
TEMPLATE_ONLY_PREFIX = "workspace/reference/templates/rubric-weave/v1/"


class PromotionError(RuntimeError):
    pass


def git(workbench: Path, *args: str, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", "-C", str(workbench), *args],
        capture_output=True,
        check=False,
        text=not binary,
    )
    if result.returncode:
        stderr = result.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        raise PromotionError(stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_target(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts:
        raise PromotionError(f"unsafe target path: {relative}")
    target = (REPO_ROOT / Path(*pure.parts)).resolve()
    try:
        target.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise PromotionError(f"target escapes repository: {relative}") from exc
    return target


def selected_sources(workbench: Path, commit: str) -> list[str]:
    selected = set(SOURCE_FILES)
    for tree in SOURCE_TREES:
        output = git(workbench, "ls-tree", "-r", "--name-only", commit, "--", tree)
        assert isinstance(output, str)
        selected.update(line for line in output.splitlines() if line)
    missing = []
    for source in sorted(selected):
        result = subprocess.run(
            ["git", "-C", str(workbench), "cat-file", "-e", f"{commit}:{source}"],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            missing.append(source)
    if missing:
        raise PromotionError("selected source paths missing at ref: " + ", ".join(missing))
    return sorted(selected)


def source_bytes(workbench: Path, commit: str, source: str) -> bytes:
    data = git(workbench, "show", f"{commit}:{source}", binary=True)
    assert isinstance(data, bytes)
    return data


def read_pin() -> dict:
    if not PIN_PATH.exists():
        raise PromotionError(f"pin not found: {PIN_PATH.relative_to(REPO_ROOT)}")
    record = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    if record.get("schema") != PIN_SCHEMA:
        raise PromotionError(f"unsupported pin schema: {record.get('schema')!r}")
    if record.get("accepted_producer_commit") != ACCEPTED_PRODUCER_COMMIT:
        raise PromotionError("pin does not retain the accepted producer commit")
    return record


def check_targets(pin: dict) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    seen_sources: set[str] = set()
    if pin.get("accepted_producer_commit") != ACCEPTED_PRODUCER_COMMIT:
        errors.append("pin does not retain the accepted producer commit")
    for entry in pin.get("files", []):
        source_name = entry.get("source")
        target_name = entry.get("target")
        if not isinstance(source_name, str) or source_name in seen_sources:
            errors.append(f"invalid or duplicate source: {source_name!r}")
        else:
            seen_sources.add(source_name)
        if not isinstance(target_name, str) or target_name in seen:
            errors.append(f"invalid or duplicate target: {target_name!r}")
            continue
        seen.add(target_name)
        target = safe_target(target_name)
        if not target.is_file():
            errors.append(f"missing target: {target_name}")
            continue
        actual = sha256(target.read_bytes())
        if actual != entry.get("sha256"):
            errors.append(f"target drift: {target_name}")
    manifest_target = safe_target(
        "workspace/reference/templates/rubric-weave/v1/manifest.json"
    )
    if manifest_target.is_file():
        try:
            manifest = json.loads(manifest_target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors.append("template manifest is unreadable")
        else:
            producer = manifest.get("accepted_producer")
            if (
                not isinstance(producer, dict)
                or producer.get("commit") != pin.get("accepted_producer_commit")
            ):
                errors.append(
                    "template manifest and pin disagree on accepted producer"
                )
    return errors


def compare_accepted_producer(workbench: Path, commit: str) -> list[str]:
    errors: list[str] = []
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(workbench),
            "merge-base",
            "--is-ancestor",
            ACCEPTED_PRODUCER_COMMIT,
            commit,
        ],
        capture_output=True,
        check=False,
    )
    if ancestor.returncode:
        errors.append("accepted producer commit is not an ancestor of the source ref")
        return errors
    for source in selected_sources(workbench, commit):
        if source in TEMPLATE_ONLY_SOURCES or source.startswith(TEMPLATE_ONLY_PREFIX):
            continue
        result = subprocess.run(
            [
                "git",
                "-C",
                str(workbench),
                "cat-file",
                "-e",
                f"{ACCEPTED_PRODUCER_COMMIT}:{source}",
            ],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            errors.append(f"accepted producer lacks pinned source: {source}")
            continue
        if source_bytes(workbench, commit, source) != source_bytes(
            workbench, ACCEPTED_PRODUCER_COMMIT, source
        ):
            errors.append(f"producer semantics changed after acceptance: {source}")
    return errors


def compare_source(workbench: Path, ref: str, pin: dict) -> list[str]:
    commit_value = git(workbench, "rev-parse", f"{ref}^{{commit}}")
    assert isinstance(commit_value, str)
    commit = commit_value.strip()
    errors: list[str] = []
    selected = selected_sources(workbench, commit)
    pinned_sources = [entry["source"] for entry in pin.get("files", [])]
    if selected != pinned_sources:
        errors.append("selected source inventory differs from the pin")
    pinned_by_source = {entry["source"]: entry for entry in pin.get("files", [])}
    for source in selected:
        expected = pinned_by_source.get(source, {}).get("sha256")
        actual = sha256(source_bytes(workbench, commit, source))
        if expected != actual:
            errors.append(f"upstream drift at {commit[:12]}: {source}")
    errors.extend(compare_accepted_producer(workbench, commit))
    return errors


def update_pin(workbench: Path, ref: str) -> dict:
    commit_value = git(workbench, "rev-parse", f"{ref}^{{commit}}")
    assert isinstance(commit_value, str)
    commit = commit_value.strip()
    semantic_errors = compare_accepted_producer(workbench, commit)
    if semantic_errors:
        raise PromotionError("; ".join(semantic_errors))
    timestamp_value = git(workbench, "show", "-s", "--format=%cI", commit)
    assert isinstance(timestamp_value, str)

    files = []
    for source in selected_sources(workbench, commit):
        data = source_bytes(workbench, commit, source)
        target_name = RENAMED_SOURCES.get(source, source)
        target = safe_target(target_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files.append(
            {
                "source": source,
                "target": target_name,
                "sha256": sha256(data),
            }
        )

    pin = {
        "schema": PIN_SCHEMA,
        "source_repository": SOURCE_REMOTE,
        "source_branch": "main",
        "source_commit": commit,
        "accepted_producer_commit": ACCEPTED_PRODUCER_COMMIT,
        "source_committed_at": timestamp_value.strip(),
        "policy": "byte-identical mechanical promotion; behavior changes upstream first",
        "files": files,
    }
    PIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PIN_PATH.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    return pin


def emit_errors(errors: Iterable[str]) -> int:
    rows = list(errors)
    if not rows:
        return 0
    for row in rows:
        print(f"ERROR: {row}", file=sys.stderr)
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workbench",
        type=Path,
        help="path to a coursecraft_workbench checkout (required for promotion or source comparison)",
    )
    parser.add_argument("--ref", help="explicit reviewed Workbench ref for --update-pin")
    parser.add_argument(
        "--compare-ref",
        help="compare the selected source surface at this Workbench ref with the current pin",
    )
    parser.add_argument("--update-pin", action="store_true", help="materialize sources and replace the pin")
    parser.add_argument("--check", action="store_true", help="verify vendored targets (the default)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.update_pin:
        if not args.workbench or not args.ref:
            raise PromotionError("--update-pin requires --workbench and --ref")
        pin = update_pin(args.workbench.resolve(), args.ref)
        print(f"promoted {len(pin['files'])} files from {pin['source_commit']}")
    else:
        pin = read_pin()

    errors = check_targets(pin)
    if args.compare_ref:
        if not args.workbench:
            raise PromotionError("--compare-ref requires --workbench")
        errors.extend(compare_source(args.workbench.resolve(), args.compare_ref, pin))
    if errors:
        return emit_errors(errors)
    print(f"vendor pin OK: {len(pin['files'])} files at {pin['source_commit'][:12]}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, json.JSONDecodeError, PromotionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
