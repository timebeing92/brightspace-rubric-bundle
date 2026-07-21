#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from zipfile import ZipFile


def _choose_candidate(candidates: list[str], label: str) -> str:
    if not candidates:
        raise ValueError(f"Could not find {label}.")
    candidates = sorted(candidates, key=lambda value: (value.count("/"), len(value), value))
    best = candidates[0]
    equally_good = [candidate for candidate in candidates if candidate.count("/") == best.count("/") and len(candidate) == len(best)]
    if len(equally_good) > 1:
        raise ValueError(f"Found multiple equally plausible {label} candidates: {equally_good}")
    return best


def _find_in_directory(input_dir: Path) -> tuple[Path, Path]:
    manifest_candidates = [
        path
        for path in input_dir.rglob("imsmanifest.xml")
        if path.is_file()
    ]
    orgunit_candidates = [
        path
        for path in input_dir.rglob("orgunitconfig.xml")
        if path.is_file() and path.parent.name == "orgunitconfig"
    ]

    if not manifest_candidates:
        raise ValueError("Could not find imsmanifest.xml inside the export directory.")
    if not orgunit_candidates:
        raise ValueError("Could not find orgunitconfig/orgunitconfig.xml inside the export directory.")

    manifest = sorted(manifest_candidates, key=lambda path: (len(path.relative_to(input_dir).parts), len(str(path)), str(path)))[0]
    orgunit = sorted(orgunit_candidates, key=lambda path: (len(path.relative_to(input_dir).parts), len(str(path)), str(path)))[0]
    return manifest, orgunit


def extract_course_context(input_path: Path, output_dir: Path, force: bool = False) -> tuple[Path, Path]:
    if output_dir.exists():
        if not force:
            raise ValueError(f"Output directory already exists: {output_dir}. Re-run with --force to replace it.")
        shutil.rmtree(output_dir)

    (output_dir / "orgunitconfig").mkdir(parents=True, exist_ok=True)

    if input_path.is_dir():
        manifest_source, orgunit_source = _find_in_directory(input_path)
        manifest_dest = output_dir / "imsmanifest.xml"
        orgunit_dest = output_dir / "orgunitconfig" / "orgunitconfig.xml"
        shutil.copy2(manifest_source, manifest_dest)
        shutil.copy2(orgunit_source, orgunit_dest)
        return manifest_dest, orgunit_dest

    if input_path.is_file() and input_path.suffix.lower() == ".zip":
        with ZipFile(input_path) as zf:
            names = [name for name in zf.namelist() if not name.endswith("/")]
            manifest_name = _choose_candidate(
                [name for name in names if name.endswith("imsmanifest.xml")],
                "imsmanifest.xml",
            )
            orgunit_name = _choose_candidate(
                [name for name in names if name.endswith("orgunitconfig/orgunitconfig.xml")],
                "orgunitconfig/orgunitconfig.xml",
            )

            manifest_dest = output_dir / "imsmanifest.xml"
            orgunit_dest = output_dir / "orgunitconfig" / "orgunitconfig.xml"
            manifest_dest.write_bytes(zf.read(manifest_name))
            orgunit_dest.write_bytes(zf.read(orgunit_name))
            return manifest_dest, orgunit_dest

    raise ValueError("Input must be either a Brightspace export directory or a .zip file.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Extract the two course-context files needed by this repo "
            "(imsmanifest.xml and orgunitconfig/orgunitconfig.xml) "
            "from a Brightspace export folder or zip."
        )
    )
    parser.add_argument("--input", required=True, help="Path to a Brightspace export folder or zip file.")
    parser.add_argument("--output-dir", required=True, help="Directory where the small course-context stub should be written.")
    parser.add_argument("--force", action="store_true", help="Replace the output directory if it already exists.")
    args = parser.parse_args()

    manifest_dest, orgunit_dest = extract_course_context(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        force=args.force,
    )

    print(f"manifest_path={manifest_dest}")
    print(f"orgunitconfig_path={orgunit_dest}")


if __name__ == "__main__":
    main()
