#!/usr/bin/env python3
"""Build an immutable bundle release asset from one explicit git ref."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILES = (
    "workspace/reference/schemas/rubrics/rubrics_schema.json",
    "workspace/reference/schemas/progress/progress_events_schema.json",
)
RUNTIME_FILES = (
    "scripts/run_rubric_bundle.py",
    "scripts/extract_rubrics_to_workbook.py",
    "scripts/rubrics_to_docx.py",
    "scripts/common_xml.py",
)
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
    if text.startswith("git@") and ":" in text:
        host_path = text.split("@", 1)[1]
        host, path = host_path.split(":", 1)
        return f"https://{host}/{path}"
    if text.startswith(("http://", "https://")):
        parts = urlsplit(text)
        host = parts.hostname or parts.netloc
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    return text


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


def release_capabilities(root: Path) -> dict[str, dict[str, Any]]:
    """Refuse to advertise the Unravel door without its runtime hooks."""
    required_markers = {
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
    for relative, markers in required_markers.items():
        source = (root / relative).read_text(encoding="utf-8")
        missing = [marker for marker in markers if marker not in source]
        if missing:
            raise RuntimeError(
                f"Selected bundle lacks Unravel release markers in {relative}: "
                + ", ".join(missing)
            )
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
            "runtime_files": list(RUNTIME_FILES),
        }
    }


def normalized_tar_gz(source: Path, output: Path, prefix: str) -> None:
    """Write a reproducible gzip-compressed tar archive."""
    with output.open("wb") as raw:
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
    checksum_path.write_text(f"{checksum}  {asset.name}\n", encoding="utf-8")
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
