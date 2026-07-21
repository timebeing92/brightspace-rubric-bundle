#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path

from rubric_package_lib import build_package


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a minimal Brightspace rubric-only package from supported markdown or JSON. "
            "This script generates the XML for you; hand-editing XML is not required."
        )
    )
    parser.add_argument("--input", required=True, help="Path to a rubric input file (.md, .txt, or .json).")
    parser.add_argument("--output-dir", required=True, help="Directory where the package, zip, and review artifacts will be written.")
    parser.add_argument("--context-dir", help="Directory containing imsmanifest.xml and orgunitconfig/orgunitconfig.xml from a Brightspace export.")
    parser.add_argument("--orgunit-identifier", help="Explicit org unit identifier.")
    parser.add_argument("--default-nav", help="Explicit default navbar name.")
    parser.add_argument("--default-homepage", help="Explicit default homepage name.")
    parser.add_argument("--title", help="Explicit course title for manifest metadata.")
    parser.add_argument("--keyword", help="Explicit course keyword for manifest metadata.")
    parser.add_argument("--force", action="store_true", help="Replace the output directory if it already exists.")
    args = parser.parse_args()

    cli_overrides = {
        "identifier": args.orgunit_identifier,
        "default_nav": args.default_nav,
        "default_homepage": args.default_homepage,
        "title": args.title,
        "keyword": args.keyword,
    }

    result = build_package(
        input_path=Path(args.input),
        output_dir=Path(args.output_dir),
        context_dir=Path(args.context_dir) if args.context_dir else None,
        cli_overrides=cli_overrides,
        force=args.force,
    )

    print(f"output_dir={result['output_dir']}")
    print(f"package_dir={result['package_dir']}")
    print(f"zip_path={result['zip_path']}")
    print(f"mapping_path={result['mapping_path']}")
    print(f"normalized_json_path={result['normalized_json_path']}")


if __name__ == "__main__":
    main()
