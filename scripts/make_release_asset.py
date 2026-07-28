#!/usr/bin/env python3
"""Build an immutable bundle release asset from one explicit git ref."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
sys.dont_write_bytecode = True
import rubric_loom_templates as loom_templates

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILES = (
    "workspace/reference/schemas/rubrics/rubrics_schema.json",
    "workspace/reference/schemas/rubrics/rubric_authoring_schema.json",
    "workspace/reference/schemas/progress/progress_events_schema.json",
    "workspace/reference/schemas/course/run_identity_schema.json",
)
UNRAVEL_RUNTIME_FILES = (
    "scripts/run_rubric_bundle.py",
    "scripts/extract_rubrics_to_workbook.py",
    "scripts/rubrics_to_docx.py",
    "scripts/common_xml.py",
)
WEAVE_RUNTIME_FILES = (
    "scripts/run_weave_bundle.py",
    "scripts/make_rubric_package.py",
    "scripts/rubric_authoring.py",
    "scripts/rubric_package_lib.py",
    "scripts/validate_rubric_package.py",
    "scripts/extract_rubrics_to_workbook.py",
    "scripts/common_xml.py",
    "upstream/workbench_pin.json",
)
TERMINAL_RUNTIME_FILES = (
    "scripts/rubric_loom_wizard.py",
    "scripts/rubric_loom_weave.py",
    "scripts/rubric_loom_templates.py",
    "scripts/loom_progress.py",
    "scripts/loom_ui.py",
    "scripts/loom_art.py",
    "scripts/release_check.py",
    "launch_rubric_loom.command",
)
INSTALL_RUNTIME_FILES = (
    "scripts/bootstrap_env.py",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-lock.txt",
)
RUNTIME_FILES = tuple(
    dict.fromkeys(
        UNRAVEL_RUNTIME_FILES
        + WEAVE_RUNTIME_FILES
        + TERMINAL_RUNTIME_FILES
        + INSTALL_RUNTIME_FILES
    )
)
REQUIREMENTS_LOCK = "requirements-lock.txt"
SBOM_PATH = "SBOM.json"
SBOM_SCHEMA = "coursecraft.bundle_sbom/1"
UNRAVEL_ENTRY_POINT = "scripts/run_rubric_bundle.py"
UNRAVEL_STEPS = (
    "Locate rubric evidence",
    "Extract rubric grids",
    "Validate rubric contract",
    "Render rubric review DOCX",
)
UNRAVEL_ARTIFACT_SUFFIXES = ("__rubrics.xlsx", "__rubrics.json", "__rubrics.docx")
UNRAVEL_EXIT_CODES = {
    "0": "success",
    "1": "step failure",
    "2": "usage or environment error",
    "3": "no rubric evidence found in the source",
}
WEAVE_ENTRY_POINT = "scripts/run_weave_bundle.py"
WEAVE_TERMINAL_ENTRY_POINT = "scripts/rubric_loom_wizard.py"
WEAVE_STEPS = (
    "Inspect source",
    "Normalize authoring contract",
    "Validate authoring contract",
    "Build rubric-only package",
    "Validate rubric package",
    "Write final run receipt",
)
WEAVE_EXIT_CODES = {
    "0": "success",
    "1": "producer or verification failure",
    "2": "usage, environment, or authoring-policy refusal",
}
WEAVE_OUTPUT_ARTIFACTS = (
    {
        "key": "import_zip",
        "path": "rubric_package.zip",
        "role": "rubric_import_package",
        "required": True,
        "primary": True,
    },
    {
        "key": "rubrics_xml",
        "path": "rubrics_d2l.xml",
        "role": "rubrics_xml_companion",
        "required": True,
        "primary": False,
    },
    {
        "key": "normalized_authoring_json",
        "path": "normalized_rubric_authoring.json",
        "role": "normalized_authoring_contract",
        "required": True,
        "primary": False,
    },
    {
        "key": "mapping_report",
        "path": "rubric_mapping.md",
        "role": "mapping_review",
        "required": True,
        "primary": False,
    },
    {
        "key": "review_report",
        "path": "conversion_review.md",
        "role": "docx_conversion_review",
        "required": False,
        "primary": False,
    },
    {
        "key": "diagnostics_json",
        "path": "diagnostics.json",
        "role": "diagnostics",
        "required": True,
        "primary": False,
    },
    {
        "key": "run_identity",
        "path": "run_receipt.json",
        "role": "bundle_run_receipt",
        "required": True,
        "primary": False,
    },
)


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {message}")
    return result.stdout.strip()


def resolve_commit(repo: Path, ref: str) -> str:
    return run_git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def require_clean(repo: Path) -> None:
    if run_git(repo, "status", "--porcelain"):
        raise RuntimeError(f"release repo is dirty: {repo}")


def normalized_remote(value: str) -> str:
    text = value.strip()
    if "@" in text and ":" in text and "://" not in text:
        host_path = text.split("@", 1)[1]
        host, path = host_path.split(":", 1)
        path = path.split("?", 1)[0].split("#", 1)[0]
        return f"https://{host}/{path}"
    parts = urlsplit(text)
    if parts.scheme in {"http", "https", "ssh", "git"}:
        host = parts.hostname or parts.netloc
        if parts.port:
            host += f":{parts.port}"
        scheme = "https" if parts.scheme in {"ssh", "git"} else parts.scheme
        return urlunsplit((scheme, host, parts.path, "", ""))
    # A release manifest must never expose a local path or an opaque remote
    # carrying credentials. Preserve only a non-sensitive basename so scratch
    # and air-gapped builds retain an honest local provenance label.
    local_path = (parts.path or text).replace("\\", "/").rstrip("/")
    candidate = local_path.rsplit("/", 1)[-1]
    if parts.scheme not in {"", "file"} and not (
        len(parts.scheme) == 1 and len(text) > 1 and text[1] == ":"
    ):
        candidate = "repository"
    return f"local:{candidate or 'repository'}"


def export_ref(repo: Path, commit: str, destination: Path) -> None:
    destination.mkdir(parents=True)
    archive = subprocess.Popen(
        ["git", "-C", str(repo), "archive", commit], stdout=subprocess.PIPE
    )
    assert archive.stdout is not None
    subprocess.run(
        ["tar", "-x", "-C", str(destination)],
        stdin=archive.stdout,
        check=True,
    )
    if archive.wait() != 0:
        raise RuntimeError(f"git archive failed for {commit}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def contract_receipt(root: Path) -> list[dict[str, str]]:
    rows = []
    for relative in CONTRACT_FILES:
        path = root / relative
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "schema": str(payload.get("$id") or ""),
                "path": relative,
                "sha256": sha256_file(path),
            }
        )
    return rows


def runtime_receipt(root: Path) -> list[dict[str, str]]:
    """Receipt the exact orchestrator and extraction entry points shipped."""
    return [
        {"path": relative, "sha256": sha256_file(root / relative)}
        for relative in RUNTIME_FILES
    ]


def template_catalog_receipt(root: Path) -> dict[str, Any]:
    """Validate every release template and return its exact pinned metadata."""

    try:
        catalog = loom_templates.load_catalog(root)
    except loom_templates.TemplateIntegrityError as exc:
        raise RuntimeError(f"Selected bundle lacks valid Weave templates: {exc}") from exc
    record = catalog.release_record()
    manifest = root / catalog.manifest_path
    record["manifest_sha256"] = sha256_file(manifest)
    return record


def sbom_document(root: Path) -> dict[str, Any]:
    lock_path = root / REQUIREMENTS_LOCK
    components: list[dict[str, str]] = []
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.count("==") != 1:
            raise RuntimeError(
                f"{REQUIREMENTS_LOCK} contains an unsupported requirement: {stripped}"
            )
        name, version = stripped.split("==", 1)
        if not name or not version:
            raise RuntimeError(
                f"{REQUIREMENTS_LOCK} contains an incomplete requirement: {stripped}"
            )
        normalized_name = name.lower().replace("_", "-")
        components.append(
            {
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{normalized_name}@{version}",
            }
        )
    components.sort(key=lambda item: (item["name"].lower(), item["version"]))
    template_catalog = template_catalog_receipt(root)
    template_assets = [
        {
            **dict(item),
            "asset_type": "editable_template",
        }
        for item in template_catalog["templates"]
    ]
    return {
        "schema": SBOM_SCHEMA,
        "source": {
            "path": REQUIREMENTS_LOCK,
            "sha256": sha256_file(lock_path),
        },
        "component_count": len(components),
        "components": components,
        "asset_count": len(template_assets),
        "assets": template_assets,
    }


def write_sbom(root: Path) -> Path:
    path = root / SBOM_PATH
    path.write_text(
        json.dumps(sbom_document(root), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def sbom_receipt(root: Path) -> dict[str, Any]:
    path = root / SBOM_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "schema": str(payload.get("schema") or ""),
        "path": SBOM_PATH,
        "sha256": sha256_file(path),
        "component_count": int(payload.get("component_count") or 0),
        "asset_count": int(payload.get("asset_count") or 0),
    }


def release_capabilities(root: Path) -> dict[str, dict[str, Any]]:
    """Gate Unravel and Weave independently against their shipped runtime."""
    unravel_markers = {
        UNRAVEL_ENTRY_POINT: (
            "--progress-events",
            "coursecraft.progress/1",
            "rubrics_d2l.xml",
            "no {RUBRIC_XML_NAME} found in the source; nothing to unravel",
            "exit_code=3",
            *UNRAVEL_STEPS,
        ),
        "scripts/extract_rubrics_to_workbook.py": (
            "--json-output",
            "coursecraft.rubrics/1",
        ),
    }
    for relative, markers in unravel_markers.items():
        path = root / relative
        if not path.is_file():
            raise RuntimeError(
                f"Selected bundle lacks Unravel runtime file: {relative}"
            )
        source = path.read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in source]
        if missing:
            raise RuntimeError(
                f"Selected bundle lacks Unravel release markers in {relative}: "
                + ", ".join(missing)
            )

    weave_markers = {
        WEAVE_ENTRY_POINT: (
            "--preflight",
            "--progress-events",
            "coursecraft.progress/1",
            "coursecraft.run/1",
            "manual_only",
            *WEAVE_STEPS,
        ),
        "scripts/make_rubric_package.py": (
            "coursecraft.rubric_authoring_preflight/1",
            "--allow-even-spacing",
            "--allow-equal-weights",
        ),
        WEAVE_TERMINAL_ENTRY_POINT: (
            "--door",
            "--approve-weave",
            "--check-for-updates",
            "--list-templates",
            "--copy-template",
            "--template-destination",
            "loom_progress",
        ),
        "scripts/rubric_loom_weave.py": (
            "run_weave_bundle.py",
            "Type WEAVE",
            "grounded_outputs",
            "expected-source-sha256",
            "Activity attachment remains manual",
        ),
        "scripts/rubric_loom_templates.py": (
            "coursecraft.rubric_weave_template_manifest/1",
            "copy_template",
            "release_path",
            "upstream_path",
        ),
        "scripts/loom_progress.py": ("coursecraft.progress/1",),
        "scripts/release_check.py": (
            "brightspace-rubric-bundle/releases/latest",
            "coursecraft.rubric_loom_release_check/1",
        ),
        "scripts/bootstrap_env.py": (
            "--dev",
            "requirements.txt",
            "requirements-dev.txt",
            "requirements-lock.txt",
        ),
    }
    for relative, markers in weave_markers.items():
        path = root / relative
        if not path.is_file():
            raise RuntimeError(
                f"Selected bundle lacks Weave runtime file: {relative}"
            )
        source = (root / relative).read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in source]
        if missing:
            raise RuntimeError(
                f"Selected bundle lacks Weave release markers in {relative}: "
                + ", ".join(missing)
            )
    for relative in WEAVE_RUNTIME_FILES:
        if not (root / relative).is_file():
            raise RuntimeError(
                f"Selected bundle lacks Weave runtime file: {relative}"
            )
    for relative in TERMINAL_RUNTIME_FILES + INSTALL_RUNTIME_FILES:
        if not (root / relative).is_file():
            raise RuntimeError(
                f"Selected bundle lacks Weave terminal runtime file: {relative}"
            )
    pin = json.loads(
        (root / "upstream/workbench_pin.json").read_text(encoding="utf-8")
    )
    if (
        pin.get("schema") != "coursecraft.workbench_vendor_pin/1"
        or not isinstance(pin.get("source_commit"), str)
        or len(pin["source_commit"]) != 40
        or not isinstance(pin.get("accepted_producer_commit"), str)
        or len(pin["accepted_producer_commit"]) != 40
    ):
        raise RuntimeError("Selected bundle lacks a usable Workbench producer pin")
    pinned_entries = {
        item.get("target"): item
        for item in pin.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("target"), str)
    }
    pinned_targets = set(pinned_entries)
    required_pinned = {
        "scripts/make_rubric_package.py",
        "scripts/rubric_authoring.py",
        "scripts/rubric_package_lib.py",
        "scripts/validate_rubric_package.py",
        "workspace/reference/schemas/rubrics/rubric_authoring_schema.json",
        "workspace/reference/schemas/course/run_identity_schema.json",
    }
    if not required_pinned <= pinned_targets:
        raise RuntimeError("Selected bundle Workbench pin lacks Weave producer targets")
    for target in sorted(pinned_entries):
        entry = pinned_entries[target]
        path = root / target
        if (
            not path.is_file()
            or not isinstance(entry.get("sha256"), str)
            or sha256_file(path) != entry["sha256"]
        ):
            raise RuntimeError(
                f"Selected bundle target does not match its Workbench pin: {target}"
            )
    template_catalog = template_catalog_receipt(root)
    return {
        "unravel": {
            "status": "enabled",
            "entry_point": UNRAVEL_ENTRY_POINT,
            "source_forms": ["course_export_zip", "unpacked_export_folder", "rubrics_d2l_xml"],
            "evidence_marker": "rubrics_d2l.xml",
            "artifact_suffixes": list(UNRAVEL_ARTIFACT_SUFFIXES),
            "rubrics_contract": "coursecraft.rubrics/1",
            "progress_schema": "coursecraft.progress/1",
            "progress_flag": "--progress-events",
            "steps": list(UNRAVEL_STEPS),
            "exit_codes": dict(UNRAVEL_EXIT_CODES),
            "runtime_files": list(UNRAVEL_RUNTIME_FILES),
        },
        "weave": {
            "status": "enabled",
            "entry_point": WEAVE_ENTRY_POINT,
            "terminal_entry_point": WEAVE_TERMINAL_ENTRY_POINT,
            "source_forms": [
                "docx_rubric_table",
                "markdown_rubric_table",
                "coursecraft.rubric_authoring/1_json",
                "eligible_coursecraft.rubrics/1_json",
                "legacy_builder_json",
            ],
            "output_artifacts": [dict(item) for item in WEAVE_OUTPUT_ARTIFACTS],
            "authoring_contract": "coursecraft.rubric_authoring/1",
            "eligible_extraction_contract": "coursecraft.rubrics/1",
            "run_contract": "coursecraft.run/1",
            "progress_schema": "coursecraft.progress/1",
            "progress_flag": "--progress-events",
            "preflight_flag": "--preflight",
            "explicit_fallback_flags": [
                "--allow-even-spacing",
                "--allow-equal-weights",
            ],
            "terminal_write_approval_flag": "--approve-weave",
            "source_byte_binding": {
                "primary": "source.sha256",
                "secondary": "source.extensions.bytes",
                "build_input": "private_verified_snapshot",
                "final_check": "coursecraft.run/1 source transport fingerprint",
            },
            "templates": template_catalog,
            "template_operations": {
                "list_flag": "--list-templates",
                "copy_flag": "--copy-template",
                "destination_flag": "--template-destination",
                "replacement_flag": "--replace-template",
                "listing_writes": False,
                "selection_writes": False,
            },
            "steps": list(WEAVE_STEPS),
            "exit_codes": dict(WEAVE_EXIT_CODES),
            "activity_attachment": "manual_only",
            "producer_pin": {
                "schema": pin["schema"],
                "source_commit": pin["source_commit"],
                "accepted_producer_commit": pin["accepted_producer_commit"],
                "file_count": len(pin.get("files", [])),
            },
            "runtime_files": list(WEAVE_RUNTIME_FILES),
            "terminal_runtime_files": list(
                TERMINAL_RUNTIME_FILES + INSTALL_RUNTIME_FILES
            ),
        },
    }


def normalized_tar_gz(source: Path, output: Path, prefix: str) -> None:
    """Write a reproducible gzip-compressed tar archive."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if output.is_symlink():
        raise RuntimeError(f"refusing symlinked release output: {output.name}")
    descriptor = os.open(output, flags, 0o644)
    with os.fdopen(descriptor, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tf:
                for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
                    relative = path.relative_to(source)
                    arcname = f"{prefix}/{relative.as_posix()}"
                    info = tf.gettarinfo(str(path), arcname=arcname)
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    info.mtime = 0
                    if path.is_file():
                        with path.open("rb") as handle:
                            tf.addfile(info, handle)
                    else:
                        tf.addfile(info)


def write_text_no_follow(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if path.is_symlink():
        raise RuntimeError(f"refusing symlinked release output: {path.name}")
    descriptor = os.open(path, flags, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


def release_manifest(
    *, version: str, commit: str, ref: str, remote: str, staged_root: Path
) -> dict[str, Any]:
    return {
        "schema": "coursecraft.bundle_release/1",
        "version": version,
        "source": {
            "repository": remote,
            "ref": ref,
            "commit": commit,
        },
        "contracts": contract_receipt(staged_root),
        "runtime_files": runtime_receipt(staged_root),
        "sbom": sbom_receipt(staged_root),
        "capabilities": release_capabilities(staged_root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", required=True, help="Explicit bundle git ref")
    parser.add_argument(
        "--output-dir", type=Path, default=REPO_ROOT / "dist"
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Build the explicit ref even when the working tree is dirty",
    )
    args = parser.parse_args(argv)

    if not args.allow_dirty:
        require_clean(REPO_ROOT)
    commit = resolve_commit(REPO_ROOT, args.ref)
    try:
        version = run_git(REPO_ROOT, "show", f"{commit}:VERSION").strip()
    except RuntimeError as exc:
        raise SystemExit(f"VERSION is missing at {commit}: {exc}") from exc
    if not version:
        raise SystemExit(f"VERSION is empty at {commit}")
    remote = normalized_remote(run_git(REPO_ROOT, "remote", "get-url", "origin"))
    release_name = f"brightspace-rubric-bundle-v{version}"
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    asset = output_dir / f"{release_name}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / release_name
        export_ref(REPO_ROOT, commit, staged)
        write_sbom(staged)
        manifest = release_manifest(
            version=version,
            commit=commit,
            ref=args.ref,
            remote=remote,
            staged_root=staged,
        )
        (staged / "RELEASE_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        normalized_tar_gz(staged, asset, release_name)

    checksum = sha256_file(asset)
    checksum_path = asset.with_name(asset.name + ".sha256")
    write_text_no_follow(
        checksum_path,
        f"{checksum}  {asset.name}\n",
    )
    print(json.dumps({
        "asset": str(asset),
        "asset_sha256": checksum,
        "checksum": str(checksum_path),
        "commit": commit,
        "version": version,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
