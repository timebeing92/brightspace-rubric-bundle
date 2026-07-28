#!/usr/bin/env python3
"""Run the Weave door through the byte-pinned Workbench producer.

Accepted sources are supported DOCX rubric tables, Markdown rubric tables,
coursecraft.rubric_authoring/1 JSON, eligible coursecraft.rubrics/1 JSON, and
the documented legacy builder JSON shape. This orchestrator owns process
sequencing and coursecraft.progress/1 only. It does not parse or reinterpret
rubric semantics.

Exit codes: 0 success, 1 producer or verification failure, 2 usage,
environment, or authoring-policy refusal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any

from jsonschema import Draft7Validator


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
PIN_PATH = REPO_ROOT / "upstream/workbench_pin.json"
RUN_SCHEMA_PATH = REPO_ROOT / "workspace/reference/schemas/course/run_identity_schema.json"
PROGRESS_SCHEMA_PATH = (
    REPO_ROOT / "workspace/reference/schemas/progress/progress_events_schema.json"
)
VERSION_PATH = REPO_ROOT / "VERSION"
RELEASE_MANIFEST_PATH = REPO_ROOT / "RELEASE_MANIFEST.json"
PROGRESS_SCHEMA = "coursecraft.progress/1"
ACCEPTED_PRODUCER_COMMIT = "71552e912b79d73a00b4d70fd97bd32386fbe2a4"
ALLOWED_SUFFIXES = {".docx", ".json", ".md", ".markdown"}

STEP_INSPECT = "Inspect source"
STEP_NORMALIZE = "Normalize authoring contract"
STEP_CONTRACT = "Validate authoring contract"
STEP_BUILD = "Build rubric-only package"
STEP_PACKAGE = "Validate rubric package"
STEP_RECEIPT = "Write final run receipt"
STEPS = [
    STEP_INSPECT,
    STEP_NORMALIZE,
    STEP_CONTRACT,
    STEP_BUILD,
    STEP_PACKAGE,
    STEP_RECEIPT,
]


class StepFailure(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class Reporter:
    def __init__(self, events: bool, label: str) -> None:
        self.events = events
        self.label = label
        self.total = len(STEPS)

    def _emit(self, payload: dict[str, Any]) -> None:
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    def run_start(self) -> None:
        if self.events:
            self._emit(
                {
                    "event": "run_start",
                    "schema": PROGRESS_SCHEMA,
                    "label": self.label,
                    "total": self.total,
                    "steps": STEPS,
                }
            )
        else:
            print(f"Rubric Loom — Weave: {self.label} ({self.total} steps)")

    def step_start(self, index: int) -> float:
        if self.events:
            self._emit(
                {
                    "event": "step_start",
                    "index": index,
                    "total": self.total,
                    "label": STEPS[index - 1],
                }
            )
        else:
            print(f"[{index}/{self.total}] {STEPS[index - 1]}")
        return time.monotonic()

    def step_end(
        self,
        index: int,
        started: float,
        status: str,
        message: str | None = None,
    ) -> None:
        seconds = round(time.monotonic() - started, 3)
        if self.events:
            payload: dict[str, Any] = {
                "event": "step_end",
                "index": index,
                "status": status,
                "seconds": seconds,
            }
            if message:
                payload["message"] = message
            self._emit(payload)
        elif status != "ok":
            print(f"    step failed: {message}", file=sys.stderr)

    def run_end_ok(
        self,
        output_dir: Path,
        outputs: dict[str, str | None],
        rubric_count: int,
        diagnostic_count: int,
    ) -> None:
        if self.events:
            self._emit(
                {
                    "event": "run_end",
                    "status": "ok",
                    "message": f"wove {rubric_count} rubric(s); nothing was imported",
                    "bundle_dir": str(output_dir),
                    "outputs": outputs,
                    "summary": {
                        "rubrics": rubric_count,
                        "diagnostics": diagnostic_count,
                    },
                    "delivery": {
                        "usable": True,
                        "empty": False,
                        "core_failures": [],
                    },
                }
            )
        else:
            print(f"Done: rubric-only import package in {output_dir}")
            print("Nothing was imported. Activity attachment remains manual.")

    def run_end_error(self, step: str, message: str) -> None:
        if self.events:
            self._emit(
                {
                    "event": "run_end",
                    "status": "error",
                    "message": message,
                    "issues": [
                        {"step": step, "status": "failed", "message": message}
                    ],
                }
            )
        else:
            print(f"ERROR: {message}", file=sys.stderr)


def sanitize_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._") or "rubric_source"


def default_label(source: Path) -> str:
    return sanitize_label(source.stem or source.name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_source_binding(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            byte_count += len(chunk)
    return digest.hexdigest(), byte_count


def source_binding(value: dict[str, Any], label: str) -> tuple[str, int]:
    source = value.get("source")
    extensions = source.get("extensions") if isinstance(source, dict) else None
    digest = source.get("sha256") if isinstance(source, dict) else None
    byte_count = extensions.get("bytes") if isinstance(extensions, dict) else None
    if isinstance(source, dict) and digest is None:
        transport = source.get("transport_fingerprint")
        if isinstance(transport, dict) and transport.get("algorithm") == "sha256":
            digest = transport.get("digest")
            byte_count = transport.get("bytes")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest.lower())
        or not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
        or byte_count < 0
    ):
        raise StepFailure(f"{label} lacks an exact source byte binding")
    return digest.lower(), byte_count


def expected_source_binding(
    args: argparse.Namespace,
) -> tuple[str, int] | None:
    digest = args.expected_source_sha256
    byte_count = args.expected_source_bytes
    if digest is None and byte_count is None:
        return None
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest.lower())
        or not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
        or byte_count < 0
    ):
        raise StepFailure(
            "expected source binding requires a SHA-256 and byte count",
            exit_code=2,
        )
    return digest.lower(), byte_count


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StepFailure(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise StepFailure(f"{label} is not a JSON object")
    return value


def diagnostic_codes(text: str) -> list[str]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return []
    diagnostics = value.get("diagnostics", []) if isinstance(value, dict) else []
    return sorted(
        {
            item["code"]
            for item in diagnostics
            if isinstance(item, dict) and isinstance(item.get("code"), str)
        }
    )


def run_child(command: list[str], timeout: float, refusal_exit: int = 1) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise StepFailure(
            f"pinned producer exceeded the step timeout of {timeout:.0f}s"
        ) from exc
    if result.returncode:
        codes = diagnostic_codes(result.stderr or result.stdout)
        if codes:
            detail = ", ".join(codes)
            raise StepFailure(
                f"pinned producer refused the source: {detail}",
                exit_code=refusal_exit,
            )
        raise StepFailure(
            f"pinned producer failed with exit {result.returncode}",
            exit_code=refusal_exit if result.returncode == 2 else 1,
        )
    return result.stdout


def producer_command(args: argparse.Namespace, output_dir: Path | None) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPTS / "make_rubric_package.py"),
        "--input",
        str(args.source),
    ]
    if output_dir is None:
        command.append("--preflight")
    else:
        command.extend(["--output-dir", str(output_dir)])
    if args.allow_even_spacing:
        command.append("--allow-even-spacing")
    if args.allow_equal_weights:
        command.append("--allow-equal-weights")
    if args.context_dir:
        command.extend(["--context-dir", str(args.context_dir)])
    if args.source_label:
        command.extend(["--source-label", args.source_label])
    for option, value in (
        ("--orgunit-identifier", args.orgunit_identifier),
        ("--default-nav", args.default_nav),
        ("--default-homepage", args.default_homepage),
        ("--title", args.title),
        ("--keyword", args.keyword),
        ("--manifest-identifier", args.manifest_identifier),
        ("--resource-prefix", args.resource_prefix),
    ):
        if value:
            command.extend([option, value])
    if args.force:
        command.append("--force")
    return command


def verify_pin() -> dict[str, Any]:
    pin = load_json(PIN_PATH, "Workbench pin")
    if pin.get("schema") != "coursecraft.workbench_vendor_pin/1":
        raise StepFailure("Workbench pin uses an unsupported schema", exit_code=2)
    if pin.get("accepted_producer_commit") != ACCEPTED_PRODUCER_COMMIT:
        raise StepFailure(
            "Workbench pin does not retain the accepted producer commit",
            exit_code=2,
        )
    required = {
        "scripts/make_rubric_package.py",
        "scripts/rubric_authoring.py",
        "scripts/rubric_package_lib.py",
        "workspace/reference/schemas/course/run_identity_schema.json",
        "workspace/reference/schemas/rubrics/rubric_authoring_schema.json",
        "workspace/reference/schemas/rubrics/rubrics_schema.json",
    }
    pinned = {
        item.get("target"): item
        for item in pin.get("files", [])
        if isinstance(item, dict)
    }
    if not required.issubset(pinned):
        raise StepFailure("Workbench pin lacks required Weave runtime markers", exit_code=2)
    for target in sorted(required):
        path = REPO_ROOT / target
        if not path.is_file() or sha256_file(path) != pinned[target].get("sha256"):
            raise StepFailure(f"vendored runtime marker failed pin verification: {target}", exit_code=2)
    return pin


def validate_preflight(value: dict[str, Any]) -> None:
    if (
        value.get("schema") != "coursecraft.rubric_authoring_preflight/1"
        or value.get("status") != "ok"
        or not isinstance(value.get("rubrics"), list)
        or not value["rubrics"]
    ):
        raise StepFailure("producer preflight did not return a usable authoring summary")
    for rubric in value["rubrics"]:
        if (
            not isinstance(rubric, dict)
            or not isinstance(rubric.get("name"), str)
            or not isinstance(rubric.get("levels"), list)
            or len(rubric["levels"]) < 2
            or not isinstance(rubric.get("criteria"), list)
            or not rubric["criteria"]
        ):
            raise StepFailure("producer preflight returned an incomplete rubric summary")
    source_binding(value, "producer preflight")


def validate_package(path: Path, timeout: float) -> None:
    stdout = run_child(
        [
            sys.executable,
            str(SCRIPTS / "validate_rubric_package.py"),
            str(path),
        ],
        timeout,
    )
    if "VALID" not in stdout.splitlines():
        raise StepFailure("pinned package validator did not report VALID")


def verify_upstream_receipt(
    receipt: dict[str, Any],
    output_dir: Path,
    expected_binding: tuple[str, int],
) -> None:
    schema = load_json(RUN_SCHEMA_PATH, "coursecraft.run/1 schema")
    errors = list(Draft7Validator(schema).iter_errors(receipt))
    if errors:
        raise StepFailure("producer run receipt violates coursecraft.run/1")
    if receipt.get("status") != "ok":
        raise StepFailure("producer run receipt is not successful")
    if source_binding(receipt, "producer run receipt") != expected_binding:
        raise StepFailure(
            "producer run receipt does not match the preflighted source bytes"
        )
    for artifact in receipt.get("emitted_files", []):
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            raise StepFailure("producer run receipt contains an invalid artifact")
        path = (output_dir / artifact["path"]).resolve()
        try:
            path.relative_to(output_dir.resolve())
        except ValueError as exc:
            raise StepFailure("producer run receipt artifact escapes the output directory") from exc
        if (
            not path.is_file()
            or path.stat().st_size != artifact.get("bytes")
            or sha256_file(path) != artifact.get("sha256")
        ):
            raise StepFailure("producer run receipt artifact checksum verification failed")


def _exact_git_identity() -> tuple[str, str | None, bool]:
    """Read Git identity only when REPO_ROOT itself is the repository.

    Release archives are commonly unpacked below another checkout (including
    the Workshop Space). Git's normal parent walk would otherwise attribute
    the bundle to that unrelated repository.
    """
    if not (REPO_ROOT / ".git").exists():
        raise RuntimeError("bundle root has no Git metadata")
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if Path(top_level).resolve() != REPO_ROOT.resolve():
        raise RuntimeError("Git top level does not match the bundle root")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if (
        len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise RuntimeError("bundle Git commit is not a full SHA")
    ref_result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    ref = ref_result.stdout.strip() or None
    dirty_result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return commit, ref, bool(dirty_result.stdout.strip())


def _release_manifest_identity(version: str | None) -> tuple[str, str, str]:
    manifest = load_json(RELEASE_MANIFEST_PATH, "bundle release manifest")
    source = manifest.get("source")
    if (
        manifest.get("schema") != "coursecraft.bundle_release/1"
        or manifest.get("version") != version
        or not isinstance(source, dict)
    ):
        raise RuntimeError("bundle release manifest identity is invalid")
    repository = source.get("repository")
    ref = source.get("ref")
    commit = source.get("commit")
    if (
        not isinstance(repository, str)
        or not repository.strip()
        or not isinstance(ref, str)
        or not ref.strip()
        or not isinstance(commit, str)
        or len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise RuntimeError("bundle release manifest source identity is invalid")
    return commit, ref, repository


def bundle_identity() -> dict[str, Any]:
    version = VERSION_PATH.read_text(encoding="utf-8").strip() if VERSION_PATH.is_file() else None
    extensions: dict[str, Any] = {
        "orchestrator_sha256": sha256_file(Path(__file__)),
    }
    try:
        commit, ref, dirty = _exact_git_identity()
        state = "git"
        extensions["identity_basis"] = "bundle_root_git"
    except (OSError, RuntimeError, subprocess.CalledProcessError):
        try:
            commit, ref, release_repository = _release_manifest_identity(version)
            dirty = False
            state = "release"
            extensions.update(
                {
                    "identity_basis": "release_manifest",
                    "release_manifest_sha256": sha256_file(RELEASE_MANIFEST_PATH),
                    "release_repository": release_repository,
                }
            )
        except (OSError, RuntimeError, json.JSONDecodeError):
            commit = None
            ref = None
            dirty = None
            state = "unknown"
            extensions.update(
                {
                    "identity_basis": "unavailable",
                    "reason": "bundle_root_git_and_release_manifest_unavailable",
                }
            )
    return {
        "component": "brightspace-rubric-bundle-weave",
        "identity_state": state,
        "version": version,
        "repository": "brightspace-rubric-bundle",
        "ref": ref,
        "commit": commit,
        "dirty": dirty,
        "extensions": extensions,
    }


def final_receipt(
    upstream: dict[str, Any],
    upstream_receipt_path: Path,
    output_dir: Path,
    pin: dict[str, Any],
    bound_source: tuple[str, int],
) -> dict[str, Any]:
    progress_sha = sha256_file(PROGRESS_SCHEMA_PATH)
    run_schema_sha = sha256_file(RUN_SCHEMA_PATH)
    upstream_sha = sha256_file(upstream_receipt_path)
    run_digest = hashlib.sha256(
        (
            str(upstream.get("run_id", ""))
            + str(pin.get("source_commit", ""))
            + sha256_file(Path(__file__))
        ).encode("utf-8")
    ).hexdigest()
    emitted = list(upstream.get("emitted_files", []))
    emitted.append(
        {
            "path": upstream_receipt_path.relative_to(output_dir).as_posix(),
            "bytes": upstream_receipt_path.stat().st_size,
            "sha256": upstream_sha,
            "media_type": "application/json",
            "contract": "coursecraft.run/1",
            "extensions": {"role": "pinned_producer_receipt"},
        }
    )
    contracts = list(upstream.get("contracts", []))
    contracts.append(
        {
            "schema": PROGRESS_SCHEMA,
            "schema_path": "workspace/reference/schemas/progress/progress_events_schema.json",
            "sha256": progress_sha,
            "extensions": {"role": "orchestrator_progress"},
        }
    )
    receipt = {
        "schema": "coursecraft.run/1",
        "run_id": f"cc:run:{run_digest[:24]}",
        "status": "ok",
        "started_at": None,
        "finished_at": None,
        "source": upstream["source"],
        "producer": bundle_identity(),
        "contracts": contracts,
        "parameters": {
            "workbench_source_commit": pin["source_commit"],
            "accepted_producer_commit": pin.get("accepted_producer_commit"),
            "preflight_source_sha256": bound_source[0],
            "preflight_source_bytes": bound_source[1],
            "upstream_parameters_sha256": hashlib.sha256(
                json_bytes(upstream.get("parameters", {}))
            ).hexdigest(),
        },
        "steps": [
            {
                "name": name,
                "status": "completed",
                "started_at": None,
                "finished_at": None,
                "artifact_paths": (
                    []
                    if name in {STEP_INSPECT, STEP_NORMALIZE, STEP_CONTRACT}
                    else (
                        ["rubric_package.zip", "rubrics_d2l.xml"]
                        if name == STEP_BUILD
                        else (
                            ["rubric_package.zip"]
                            if name == STEP_PACKAGE
                            else ["producer_run_receipt.json", "run_receipt.json"]
                        )
                    )
                ),
                "diagnostic_ids": [],
                "notes": (
                    ["No activity payloads were generated or modified."]
                    if name == STEP_BUILD
                    else []
                ),
                "extensions": {},
            }
            for name in STEPS
        ],
        "emitted_files": emitted,
        "receipt_path": "run_receipt.json",
        "diagnostics": upstream.get("diagnostics", []),
        "extensions": {
            "workbench_pin": {
                "source_commit": pin["source_commit"],
                "accepted_producer_commit": pin.get("accepted_producer_commit"),
                "file_count": len(pin.get("files", [])),
            },
            "upstream_run_id": upstream.get("run_id"),
            "upstream_run_receipt_sha256": upstream_sha,
            "activity_attachment": "manual_only",
        },
    }
    schema = load_json(RUN_SCHEMA_PATH, "coursecraft.run/1 schema")
    errors = list(Draft7Validator(schema).iter_errors(receipt))
    if errors:
        raise StepFailure("final run receipt violates coursecraft.run/1")
    return receipt


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--label")
    parser.add_argument("--source-label")
    parser.add_argument("--context-dir", type=Path)
    parser.add_argument("--orgunit-identifier")
    parser.add_argument("--default-nav")
    parser.add_argument("--default-homepage")
    parser.add_argument("--title")
    parser.add_argument("--keyword")
    parser.add_argument("--manifest-identifier")
    parser.add_argument("--resource-prefix")
    parser.add_argument("--allow-even-spacing", action="store_true")
    parser.add_argument("--allow-equal-weights", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--preflight",
        "--peek",
        action="store_true",
        dest="preflight",
        help="emit only the pinned producer preflight JSON",
    )
    parser.add_argument(
        "--progress-events",
        action="store_true",
        help="emit coursecraft.progress/1 NDJSON for build runs",
    )
    parser.add_argument("--step-timeout", type=float, default=900.0)
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-source-bytes", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.preflight:
        try:
            verify_pin()
        except StepFailure as failure:
            print(
                json.dumps(
                    {
                        "schema": "coursecraft.rubric_authoring_preflight/1",
                        "status": "error",
                        "diagnostics": [
                            {
                                "id": "diag-0001",
                                "code": "VENDOR_PIN_INVALID",
                                "severity": "error",
                                "message": str(failure),
                                "location": "producer",
                                "remediation": "Restore the exact release-pinned producer files.",
                                "extensions": {},
                            }
                        ],
                    }
                ),
                file=sys.stderr,
            )
            return 2
        try:
            result = subprocess.run(
                producer_command(args, None),
                cwd=REPO_ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=args.step_timeout,
            )
        except subprocess.TimeoutExpired:
            print(
                json.dumps(
                    {
                        "schema": "coursecraft.rubric_authoring_preflight/1",
                        "status": "error",
                        "diagnostics": [
                            {
                                "id": "diag-0001",
                                "code": "PRODUCER_TIMEOUT",
                                "severity": "error",
                                "message": "The pinned producer exceeded the preflight timeout.",
                                "location": "producer",
                                "remediation": "Retry with a supported source or a larger step timeout.",
                                "extensions": {},
                            }
                        ],
                    }
                ),
                file=sys.stderr,
            )
            return 2
        stream = sys.stdout if result.returncode == 0 else sys.stderr
        print((result.stdout if result.returncode == 0 else result.stderr).strip(), file=stream)
        return result.returncode

    label = sanitize_label(args.label) if args.label else default_label(args.source)
    output_dir = (
        args.output_dir
        if args.output_dir
        else Path("output") / f"{label}__weave_bundle"
    )
    reporter = Reporter(args.progress_events, label)
    reporter.run_start()
    current_step = STEP_INSPECT
    index = 0
    started = time.monotonic()
    try:
        index = 1
        current_step = STEP_INSPECT
        started = reporter.step_start(index)
        pin = verify_pin()
        if not args.source.is_file():
            raise StepFailure("source is not a readable file", exit_code=2)
        if args.source.suffix.lower() not in ALLOWED_SUFFIXES:
            raise StepFailure(
                "source must be DOCX, Markdown, or JSON",
                exit_code=2,
            )
        reporter.step_end(index, started, "ok")

        index = 2
        current_step = STEP_NORMALIZE
        started = reporter.step_start(index)
        preflight_stdout = run_child(
            producer_command(args, None),
            args.step_timeout,
            refusal_exit=2,
        )
        try:
            preflight = json.loads(preflight_stdout)
        except json.JSONDecodeError as exc:
            raise StepFailure("producer preflight did not return JSON") from exc
        reporter.step_end(index, started, "ok")

        index = 3
        current_step = STEP_CONTRACT
        started = reporter.step_start(index)
        validate_preflight(preflight)
        bound_source = source_binding(preflight, "producer preflight")
        expected_binding = expected_source_binding(args)
        if expected_binding is not None and bound_source != expected_binding:
            raise StepFailure(
                "source bytes differ from the caller-approved preflight",
                exit_code=2,
            )
        reporter.step_end(index, started, "ok")

        index = 4
        current_step = STEP_BUILD
        started = reporter.step_start(index)
        if file_source_binding(args.source) != bound_source:
            raise StepFailure(
                "source changed after preflight; build refused",
                exit_code=2,
            )
        run_child(producer_command(args, output_dir), args.step_timeout, refusal_exit=2)
        expected = {
            "package_dir": output_dir / "package",
            "import_zip": output_dir / "rubric_package.zip",
            "rubrics_xml": output_dir / "rubrics_d2l.xml",
            "normalized_authoring_json": output_dir / "normalized_rubric_authoring.json",
            "mapping_report": output_dir / "rubric_mapping.md",
            "diagnostics_json": output_dir / "diagnostics.json",
            "producer_receipt": output_dir / "run_receipt.json",
        }
        if not all(path.exists() for path in expected.values()):
            raise StepFailure("pinned producer omitted a required Weave artifact")
        reporter.step_end(index, started, "ok")

        index = 5
        current_step = STEP_PACKAGE
        started = reporter.step_start(index)
        validate_package(expected["package_dir"], args.step_timeout)
        validate_package(expected["import_zip"], args.step_timeout)
        reporter.step_end(index, started, "ok")

        index = 6
        current_step = STEP_RECEIPT
        started = reporter.step_start(index)
        upstream = load_json(expected["producer_receipt"], "producer run receipt")
        verify_upstream_receipt(upstream, output_dir, bound_source)
        producer_receipt = output_dir / "producer_run_receipt.json"
        if producer_receipt.exists():
            producer_receipt.unlink()
        shutil.move(expected["producer_receipt"], producer_receipt)
        final = final_receipt(
            upstream,
            producer_receipt,
            output_dir,
            pin,
            bound_source,
        )
        final_path = output_dir / "run_receipt.json"
        final_path.write_bytes(json_bytes(final))
        reporter.step_end(index, started, "ok")
    except (OSError, subprocess.TimeoutExpired, StepFailure) as failure:
        wrapped = failure if isinstance(failure, StepFailure) else StepFailure(str(failure), 2)
        if index:
            reporter.step_end(index, started, "error", str(wrapped))
        reporter.run_end_error(current_step, str(wrapped))
        return wrapped.exit_code

    review_report = output_dir / "conversion_review.md"
    outputs: dict[str, str | None] = {
        "import_zip": str(expected["import_zip"]),
        "rubrics_xml": str(expected["rubrics_xml"]),
        "normalized_authoring_json": str(expected["normalized_authoring_json"]),
        "mapping_report": str(expected["mapping_report"]),
        "review_report": str(review_report) if review_report.is_file() else None,
        "diagnostics_json": str(expected["diagnostics_json"]),
        "run_identity": str(final_path),
    }
    reporter.run_end_ok(
        output_dir,
        outputs,
        rubric_count=int(preflight["rubric_count"]),
        diagnostic_count=len(preflight.get("diagnostics", [])),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
