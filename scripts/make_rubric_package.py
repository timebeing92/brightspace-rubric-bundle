#!/usr/bin/env python3
"""Strict Weave entry point for rubric authoring, preflight, and packaging."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rubric_authoring import (
    AuthoringRefusal,
    build_weave_outputs,
    normalize_source,
    preflight_summary,
)


def _print_json(value: object, stream: object = sys.stdout) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True), file=stream)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight or build a deterministic Brightspace rubric-only package "
            "from DOCX, Markdown, JSON, or eligible coursecraft.rubrics/1."
        )
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--preflight",
        "--peek",
        action="store_true",
        dest="preflight",
        help="Inspect and normalize without writing package outputs.",
    )
    parser.add_argument(
        "--allow-even-spacing",
        action="store_true",
        help="Explicitly approve an evenly spaced level scale when scoring metadata is absent.",
    )
    parser.add_argument(
        "--allow-equal-weights",
        action="store_true",
        help="Explicitly approve equal criterion weights when all criterion weights are absent.",
    )
    parser.add_argument("--context-dir", type=Path)
    parser.add_argument("--orgunit-identifier")
    parser.add_argument("--default-nav")
    parser.add_argument("--default-homepage")
    parser.add_argument("--title")
    parser.add_argument("--keyword")
    parser.add_argument("--manifest-identifier")
    parser.add_argument("--resource-prefix")
    parser.add_argument(
        "--source-label",
        help="Optional non-sensitive display label. Defaults to the generic 'rubric-source'.",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if not args.preflight and args.output_dir is None:
        parser.error("--output-dir is required unless --preflight/--peek is used.")
    try:
        if args.preflight:
            contract = normalize_source(
                args.input,
                allow_even_spacing=args.allow_even_spacing,
                allow_equal_weights=args.allow_equal_weights,
                manifest_identifier=args.manifest_identifier,
                resource_prefix=args.resource_prefix,
                source_label=args.source_label,
            )
            _print_json(preflight_summary(contract))
            return
        overrides = {
            "identifier": args.orgunit_identifier,
            "default_nav": args.default_nav,
            "default_homepage": args.default_homepage,
            "title": args.title,
            "keyword": args.keyword,
        }
        result = build_weave_outputs(
            args.input,
            args.output_dir,
            allow_even_spacing=args.allow_even_spacing,
            allow_equal_weights=args.allow_equal_weights,
            context_dir=args.context_dir,
            cli_overrides=overrides,
            manifest_identifier=args.manifest_identifier,
            resource_prefix=args.resource_prefix,
            source_label=args.source_label,
            force=args.force,
        )
    except AuthoringRefusal as exc:
        _print_json(
            {
                "schema": "coursecraft.rubric_authoring_preflight/1",
                "status": "error",
                "diagnostics": exc.diagnostics,
            },
            stream=sys.stderr,
        )
        raise SystemExit(2) from exc
    except Exception as exc:
        _print_json(
            {
                "schema": "coursecraft.rubric_authoring_preflight/1",
                "status": "error",
                "diagnostics": [
                    {
                        "id": "diag-0001",
                        "code": "PRODUCER_ERROR",
                        "severity": "error",
                        "message": "The producer could not complete the requested operation.",
                        "location": "producer",
                        "remediation": "Inspect the source and producer arguments, then run preflight again.",
                        "extensions": {"error_type": type(exc).__name__},
                    }
                ],
            },
            stream=sys.stderr,
        )
        raise SystemExit(1) from exc

    print("VALID")
    output_root = result["output_dir"]
    for key, path in result.items():
        relative = "." if key == "output_dir" else path.relative_to(output_root).as_posix()
        print(f"{key}={relative}")


if __name__ == "__main__":
    main()
