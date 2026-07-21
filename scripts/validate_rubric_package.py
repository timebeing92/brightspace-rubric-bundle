#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from rubric_package_lib import validate_package_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a minimal Brightspace rubric-only package directory or zip.")
    parser.add_argument("path", help="Path to a package directory or package zip.")
    args = parser.parse_args()

    errors, warnings, summary = validate_package_path(Path(args.path))

    if summary:
        for key, value in summary.items():
            print(f"{key}={value}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")

    if errors:
        raise SystemExit(1)
    print("VALID")


if __name__ == "__main__":
    main()
