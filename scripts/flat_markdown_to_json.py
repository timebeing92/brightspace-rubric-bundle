#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rubric_package_lib import load_rubric_contract, normalize_contract


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert supported flat markdown rubrics into the JSON contract used by the package builder."
        )
    )
    parser.add_argument("--input", required=True, help="Path to a markdown rubric file.")
    parser.add_argument("--output", required=True, help="Path for the output JSON contract.")
    parser.add_argument("--manifest-identifier", help="Optional manifest identifier to write into package metadata.")
    parser.add_argument("--resource-prefix", help="Optional resource prefix to write into package metadata.")
    args = parser.parse_args()

    contract = normalize_contract(load_rubric_contract(Path(args.input)))
    if args.manifest_identifier:
        contract["package"]["manifest_identifier"] = args.manifest_identifier
    if args.resource_prefix:
        contract["package"]["resource_prefix"] = args.resource_prefix

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
