#!/usr/bin/env python3
"""Library for building minimal Brightspace rubric-only import packages.

Ported 2026-06-12 from the standalone `brightspace-rubric-package-starter`
repo (Apr 22 snapshot), which remains untouched as the shareable original.
Consumed by build_rubric_package.py / validate_rubric_package.py /
extract_course_context.py / flat_markdown_to_json.py.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

LEVEL_MULTIPLIERS = [
    ("Advanced", 1.0),
    ("Proficient", 0.9),
    ("Developing", 0.75),
    ("Needs Improvement", 0.0),
]
DEFAULT_LEVELS = [
    {
        "name": name,
        "multiplier": multiplier,
        "sort_order": index,
        "score_source": "legacy_default",
    }
    for index, (name, multiplier) in enumerate(LEVEL_MULTIPLIERS, start=1)
]
OVERALL_LEVELS = [
    ("Needs Improvement", 4),
    ("Developing", 3),
    ("Proficient", 2),
    ("Advanced", 1),
]
DEFAULT_OVERALL_THRESHOLDS = {
    "Needs Improvement": 0.0,
    "Developing": 75.0,
    "Proficient": 90.0,
    "Advanced": 100.0,
}
REQUIRED_LEVELS = [name for name, _ in LEVEL_MULTIPLIERS]
IMS_NS = "http://www.imsglobal.org/xsd/imscp_v1p1"
IMSMD_NS = "http://www.imsglobal.org/xsd/imsmd_rootv1p2p1"
D2L_NS = "http://desire2learn.com/xsd/d2lcp_v2p0"
SCORM_NS = "http://www.adlnet.org/xsd/adlcp_rootv1p2"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _as_paragraph_html(value: str) -> str:
    text = value.strip()
    if not text:
        return "<p></p>"
    if "<" in text and ">" in text:
        return text
    return f"<p>{html.escape(text)}</p>"


def _parse_numeric_value(value: Any, field_label: str) -> float:
    text = str(value).strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError(f"Could not parse {field_label} from value: {value!r}")
    return float(match.group(0))


def _parse_weight_value(value: str) -> float:
    return _parse_numeric_value(value, "rubric weight")


def _normalize_metadata_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _format_score_value(value: float) -> str:
    return f"{value:.9f}"


def _default_overall_levels() -> list[dict[str, Any]]:
    return [
        {
            "name": level_name,
            "sort_order": sort_order,
            "range_start_value": DEFAULT_OVERALL_THRESHOLDS[level_name],
        }
        for level_name, sort_order in OVERALL_LEVELS
    ]


def infer_kind(name: str) -> str:
    lowered = name.lower()
    if "discussion" in lowered:
        return "discussion"
    if "assignment" in lowered or "checkpoint" in lowered or "project" in lowered:
        return "assignment"
    return "other"


def _normalize_header_token(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.replace("&", " and ")
    normalized = normalized.replace("%", " percent ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _header_matches(header: str, aliases: set[str]) -> bool:
    if header in aliases:
        return True
    return any(alias in header for alias in aliases if " " in alias)


def _classify_column_header(raw_header: str) -> str | None:
    if raw_header.strip() == "#":
        return "ignored"

    header = _normalize_header_token(raw_header)

    if not header:
        return None

    criterion_aliases = {
        "criterion",
        "criteria",
        "criterion name",
        "criteria name",
        "rubric criterion",
        "rubric criteria",
        "trait",
        "traits",
        "dimension",
        "dimensions",
        "category",
        "categories",
        "row name",
        "performance criterion",
        "performance criteria",
    }
    weight_aliases = {
        "weight",
        "weights",
        "criterion weight",
        "criteria weight",
        "row weight",
        "points",
        "point",
        "pts",
        "score weight",
        "percent weight",
        "weight percent",
        "max points",
    }
    ignored_aliases = {
        "number",
        "no",
        "no.",
        "row",
        "row number",
        "id",
        "identifier",
        "index",
        "sort",
        "sort order",
        "sequence",
        "item",
        "item number",
        "notes",
        "note",
        "comments",
        "comment",
        "remarks",
        "remark",
        "feedback notes",
        "evidence",
        "example",
        "examples",
    }
    advanced_aliases = {
        "advanced",
        "advanced 100",
        "advanced 100 percent",
        "exemplary",
        "excellent",
        "outstanding",
        "exceptional",
        "distinguished",
        "mastery",
        "mastery level",
        "exceeds",
        "exceeds expectations",
        "high performance",
        "high proficiency",
        "level 4",
        "4",
        "100",
        "100 percent",
    }
    proficient_aliases = {
        "proficient",
        "proficient 90",
        "proficient 90 percent",
        "meets",
        "meets expectations",
        "competent",
        "competent performance",
        "good",
        "solid",
        "effective",
        "satisfactory",
        "level 3",
        "3",
        "90",
        "90 percent",
    }
    developing_aliases = {
        "developing",
        "developing 75",
        "developing 75 percent",
        "approaching",
        "approaching expectations",
        "emerging",
        "progressing",
        "in progress",
        "fair",
        "partial",
        "partially meets",
        "needs development",
        "level 2",
        "2",
        "75",
        "75 percent",
    }
    needs_improvement_aliases = {
        "needs improvement",
        "needs improvement 0",
        "needs improvement 0 percent",
        "beginning",
        "below expectations",
        "poor",
        "limited",
        "minimal",
        "inadequate",
        "unsatisfactory",
        "not yet",
        "does not meet",
        "level 1",
        "1",
        "0",
        "0 percent",
    }

    if _header_matches(header, ignored_aliases):
        return "ignored"
    if _header_matches(header, criterion_aliases):
        return "criterion"
    if _header_matches(header, weight_aliases):
        return "weight"
    if _header_matches(header, advanced_aliases):
        return "Advanced"
    if _header_matches(header, proficient_aliases):
        return "Proficient"
    if _header_matches(header, developing_aliases):
        return "Developing"
    if _header_matches(header, needs_improvement_aliases):
        return "Needs Improvement"
    return None


def _normalize_overall_level_name(raw_name: str) -> str | None:
    semantic = _classify_column_header(raw_name)
    if semantic in REQUIRED_LEVELS:
        return semantic
    return None


def _parse_overall_levels_string(raw_value: str, rubric_name: str) -> dict[str, float]:
    text = str(raw_value).strip()
    if not text:
        raise ValueError(f"Rubric '{rubric_name}' has an empty overall threshold definition.")

    named_thresholds: dict[str, float] = {}
    named_parts = [part.strip() for part in re.split(r"[;,]", text) if part.strip()]
    if named_parts and all(("=" in part or ":" in part) for part in named_parts):
        for part in named_parts:
            name_part, value_part = re.split(r"\s*[:=]\s*", part, maxsplit=1)
            level_name = _normalize_overall_level_name(name_part)
            if level_name is None:
                raise ValueError(
                    f"Rubric '{rubric_name}' has an unrecognized overall threshold level name: {name_part!r}"
                )
            if level_name in named_thresholds:
                raise ValueError(
                    f"Rubric '{rubric_name}' defines the overall threshold for '{level_name}' more than once."
                )
            named_thresholds[level_name] = _parse_numeric_value(
                value_part, f"overall threshold for '{level_name}'"
            )
        return named_thresholds

    number_tokens = re.findall(r"-?\d+(?:\.\d+)?", text)
    if len(number_tokens) == 4:
        return {
            level_name: float(number_token)
            for (level_name, _), number_token in zip(OVERALL_LEVELS, number_tokens)
        }

    raise ValueError(
        f"Rubric '{rubric_name}' overall thresholds must be either four numbers in "
        "Needs Improvement/Developing/Proficient/Advanced order or named pairs such as "
        "'Needs Improvement=0; Developing=75; Proficient=90; Advanced=100'."
    )


def _normalize_overall_levels(raw_overall_levels: Any, rubric_name: str) -> list[dict[str, Any]]:
    if raw_overall_levels is None or raw_overall_levels == "":
        threshold_map = dict(DEFAULT_OVERALL_THRESHOLDS)
    elif isinstance(raw_overall_levels, str):
        threshold_map = _parse_overall_levels_string(raw_overall_levels, rubric_name)
    elif isinstance(raw_overall_levels, dict):
        threshold_map = {}
        for raw_name, raw_value in raw_overall_levels.items():
            level_name = _normalize_overall_level_name(str(raw_name))
            if level_name is None:
                raise ValueError(
                    f"Rubric '{rubric_name}' has an unrecognized overall threshold level name: {raw_name!r}"
                )
            if level_name in threshold_map:
                raise ValueError(
                    f"Rubric '{rubric_name}' defines the overall threshold for '{level_name}' more than once."
                )
            threshold_map[level_name] = _parse_numeric_value(
                raw_value, f"overall threshold for '{level_name}'"
            )
    elif isinstance(raw_overall_levels, list):
        threshold_map = {}
        for entry in raw_overall_levels:
            if not isinstance(entry, dict):
                raise ValueError(f"Rubric '{rubric_name}' overall_levels entries must be objects.")
            level_name = _normalize_overall_level_name(str(entry.get("name", "")))
            if level_name is None:
                raise ValueError(
                    f"Rubric '{rubric_name}' has an unrecognized overall threshold level name: {entry.get('name', '')!r}"
                )
            if level_name in threshold_map:
                raise ValueError(
                    f"Rubric '{rubric_name}' defines the overall threshold for '{level_name}' more than once."
                )
            raw_threshold = entry.get(
                "range_start_value",
                entry.get("threshold", entry.get("value", entry.get("start_value", ""))),
            )
            threshold_map[level_name] = _parse_numeric_value(
                raw_threshold, f"overall threshold for '{level_name}'"
            )
    else:
        raise ValueError(
            f"Rubric '{rubric_name}' overall_levels must be omitted, a string, an object, or a list."
        )

    missing_levels = [level_name for level_name, _ in OVERALL_LEVELS if level_name not in threshold_map]
    if missing_levels:
        raise ValueError(
            f"Rubric '{rubric_name}' is missing overall thresholds for: {', '.join(missing_levels)}"
        )

    ordered_thresholds = [threshold_map[level_name] for level_name, _ in OVERALL_LEVELS]
    if abs(ordered_thresholds[0]) > 1e-9:
        raise ValueError(
            f"Rubric '{rubric_name}' lowest overall threshold must start at 0."
        )
    if any(threshold < 0 or threshold > 100 for threshold in ordered_thresholds):
        raise ValueError(
            f"Rubric '{rubric_name}' overall thresholds must stay within the 0-100 rubric score range."
        )
    if any(later <= earlier for earlier, later in zip(ordered_thresholds, ordered_thresholds[1:])):
        raise ValueError(
            f"Rubric '{rubric_name}' overall thresholds must increase from Needs Improvement to Advanced."
        )

    return [
        {
            "name": level_name,
            "sort_order": sort_order,
            "range_start_value": threshold_map[level_name],
        }
        for level_name, sort_order in OVERALL_LEVELS
    ]


def _detect_markdown_table_column_map(title: str, header_cells: list[str]) -> dict[str, int]:
    column_map: dict[str, int] = {}
    duplicates: dict[str, list[str]] = {}
    ignored_columns: set[int] = set()
    unknown_columns: list[int] = []

    for index, raw_header in enumerate(header_cells):
        semantic = _classify_column_header(raw_header)
        if semantic is None:
            unknown_columns.append(index)
            continue
        if semantic == "ignored":
            ignored_columns.add(index)
            continue
        if semantic in column_map:
            duplicates.setdefault(semantic, [header_cells[column_map[semantic]]]).append(raw_header)
            continue
        column_map[semantic] = index

    if duplicates:
        duplicate_notes = ", ".join(
            f"{semantic}: {values}" for semantic, values in sorted(duplicates.items())
        )
        raise ValueError(f"Rubric section '{title}' has ambiguous table headers -> {duplicate_notes}")

    core_required = ["criterion", "weight"]
    core_missing = [column for column in core_required if column not in column_map]
    if core_missing:
        raise ValueError(
            f"Rubric section '{title}' is missing required semantic columns: {', '.join(core_missing)}. "
            "Use recognizable aliases such as Criterion/Criteria and Weight/Points."
        )

    missing_levels = [level for level in REQUIRED_LEVELS if level not in column_map]
    if missing_levels:
        remaining_unknown_columns = [
            index
            for index in unknown_columns
            if index not in ignored_columns and index not in column_map.values()
        ]
        recognized_level_count = sum(1 for level in REQUIRED_LEVELS if level in column_map)
        if recognized_level_count + len(remaining_unknown_columns) == 4 and len(remaining_unknown_columns) == len(missing_levels):
            for semantic_level, column_index in zip(missing_levels, remaining_unknown_columns):
                column_map[semantic_level] = column_index
        else:
            raise ValueError(
                f"Rubric section '{title}' is missing required level columns: {', '.join(missing_levels)}. "
                "Use common aliases, or provide exactly four left-to-right performance columns after criterion/weight so the parser can infer them."
            )

    return column_map


def _extract_markdown_overall_levels(metadata: dict[str, str], title: str) -> Any:
    grouped_keys = [
        key
        for key in [
            "overall_thresholds",
            "overall_levels",
            "overall_scoring",
            "overall_scoring_thresholds",
        ]
        if key in metadata
    ]
    individual_key_map = {
        "overall_needs_improvement": "Needs Improvement",
        "overall_developing": "Developing",
        "overall_proficient": "Proficient",
        "overall_advanced": "Advanced",
        "needs_improvement_threshold": "Needs Improvement",
        "developing_threshold": "Developing",
        "proficient_threshold": "Proficient",
        "advanced_threshold": "Advanced",
    }
    individual_thresholds = {
        level_name: metadata[key]
        for key, level_name in individual_key_map.items()
        if key in metadata
    }

    if grouped_keys and individual_thresholds:
        raise ValueError(
            f"Rubric section '{title}' mixes grouped and per-level overall threshold metadata. Use one form."
        )
    if len(grouped_keys) > 1:
        raise ValueError(
            f"Rubric section '{title}' defines overall thresholds more than once: {', '.join(grouped_keys)}"
        )
    if grouped_keys:
        return metadata[grouped_keys[0]]
    if individual_thresholds:
        missing_levels = [
            level_name for level_name, _ in OVERALL_LEVELS if level_name not in individual_thresholds
        ]
        if missing_levels:
            raise ValueError(
                f"Rubric section '{title}' is missing overall threshold metadata for: {', '.join(missing_levels)}"
            )
        return individual_thresholds
    return None


def parse_flat_markdown(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    rubrics: list[dict[str, Any]] = []
    section_starts = [index for index, line in enumerate(lines) if line.startswith("## ")]

    for section_number, start in enumerate(section_starts):
        end = section_starts[section_number + 1] if section_number + 1 < len(section_starts) else len(lines)
        block = lines[start:end]
        title = block[0][3:].strip()
        metadata: dict[str, str] = {}
        table_lines: list[str] = []

        for line in block[1:]:
            stripped = line.strip()
            metadata_match = re.match(r"^-\s*([^:]+):\s*(.+)$", stripped)
            if metadata_match:
                metadata_key = _normalize_metadata_key(metadata_match.group(1))
                metadata[metadata_key] = metadata_match.group(2).strip()
            elif stripped.startswith("|"):
                table_lines.append(stripped)

        if len(table_lines) < 3:
            raise ValueError(f"Rubric section '{title}' is missing a usable markdown table.")

        header = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
        column_map = _detect_markdown_table_column_map(title, header)

        criteria = []
        for row in table_lines[2:]:
            parts = [cell.strip() for cell in row.strip("|").split("|")]
            if len(parts) != len(header):
                raise ValueError(f"Rubric section '{title}' has a malformed table row: {row}")
            criteria.append(
                {
                    "name": parts[column_map["criterion"]],
                    "weight": _parse_weight_value(parts[column_map["weight"]]),
                    "levels": {
                        "Advanced": parts[column_map["Advanced"]],
                        "Proficient": parts[column_map["Proficient"]],
                        "Developing": parts[column_map["Developing"]],
                        "Needs Improvement": parts[column_map["Needs Improvement"]],
                    },
                }
            )

        rubrics.append(
            {
                "name": title,
                "kind": metadata.get("kind", infer_kind(title)),
                "source_title": metadata.get("source_title", ""),
                "source_id": metadata.get("source_id", ""),
                "grade_item_id": metadata.get("grade_item_id", ""),
                "overall_levels": _extract_markdown_overall_levels(metadata, title),
                "criteria": criteria,
            }
        )

    if not rubrics:
        raise ValueError("No rubric sections were found. Use markdown headings that start with '## '.")
    return rubrics


def load_rubric_contract(input_path: Path) -> dict[str, Any]:
    suffix = input_path.suffix.lower()
    raw_text = input_path.read_text(encoding="utf-8")

    if suffix == ".json":
        data = json.loads(raw_text)
    elif suffix in {".md", ".markdown", ".txt"}:
        data = {"package": {}, "rubrics": parse_flat_markdown(raw_text)}
    else:
        raise ValueError(f"Unsupported input format: {input_path}")

    if not isinstance(data, dict):
        raise ValueError("Top-level rubric contract must be a JSON object.")

    data.setdefault("package", {})
    data.setdefault("notes", [])
    data.setdefault("excluded_items", [])
    if not isinstance(data.get("rubrics"), list) or not data["rubrics"]:
        raise ValueError("Rubric contract must contain a non-empty 'rubrics' array.")
    return data


def normalize_contract(data: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "package": dict(data.get("package", {})),
        "notes": list(data.get("notes", [])),
        "excluded_items": list(data.get("excluded_items", [])),
        "rubrics": [],
    }

    for rubric in data["rubrics"]:
        name = str(rubric.get("name", "")).strip()
        if not name:
            raise ValueError("Every rubric must have a non-empty 'name'.")
        kind = str(rubric.get("kind", infer_kind(name))).strip() or infer_kind(name)
        criteria = rubric.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise ValueError(f"Rubric '{name}' must have a non-empty 'criteria' list.")

        normalized_criteria = []
        total_weight = 0.0
        for criterion in criteria:
            criterion_name = str(criterion.get("name", "")).strip()
            if not criterion_name:
                raise ValueError(f"Rubric '{name}' has a criterion with no name.")
            try:
                weight = float(criterion["weight"])
            except Exception as exc:
                raise ValueError(f"Criterion '{criterion_name}' in rubric '{name}' has an invalid weight.") from exc
            levels = criterion.get("levels", {})
            missing = [level_name for level_name in REQUIRED_LEVELS if level_name not in levels]
            if missing:
                raise ValueError(f"Criterion '{criterion_name}' in rubric '{name}' is missing levels: {', '.join(missing)}")
            normalized_levels = {level_name: _as_paragraph_html(str(levels[level_name])) for level_name in REQUIRED_LEVELS}
            normalized_criteria.append(
                {
                    "name": criterion_name,
                    "weight": weight,
                    "levels": normalized_levels,
                }
            )
            total_weight += weight

        if abs(total_weight - 100.0) > 1e-9:
            raise ValueError(f"Rubric '{name}' totals {total_weight} instead of 100.")

        normalized["rubrics"].append(
            {
                "name": name,
                "kind": kind,
                "source_title": str(rubric.get("source_title", "")).strip(),
                "source_id": str(rubric.get("source_id", "")).strip(),
                "grade_item_id": str(rubric.get("grade_item_id", "")).strip(),
                "overall_levels": _normalize_overall_levels(
                    rubric.get("overall_levels", rubric.get("overall_thresholds")),
                    name,
                ),
                "criteria": normalized_criteria,
            }
        )

    package = normalized["package"]
    package.setdefault("manifest_identifier", "D2L_RUBRICS_FIRST_PASS")
    package.setdefault("resource_prefix", "A1B2C3D4-E5F6-7890-ABCD-1234567890AB")
    package.setdefault("rubric_id_start", 1)
    package.setdefault("resource_code_start", 980001)
    package.setdefault("level_id_base_start", 660000)
    return normalized


def load_context_from_dir(context_dir: Path) -> dict[str, str]:
    orgunit_path = context_dir / "orgunitconfig" / "orgunitconfig.xml"
    manifest_path = context_dir / "imsmanifest.xml"
    orgunit_root = ET.parse(orgunit_path).getroot()
    manifest_root = ET.parse(manifest_path).getroot()
    ns = {"imsmd": IMSMD_NS}
    title_node = manifest_root.find(".//imsmd:title/imsmd:langstring", ns)
    keyword_node = manifest_root.find(".//imsmd:keyword/imsmd:langstring", ns)

    return {
        "identifier": orgunit_root.attrib["identifier"],
        "default_nav": orgunit_root.attrib["default_nav"],
        "default_homepage": orgunit_root.attrib["default_homepage"],
        "title": title_node.text if title_node is not None and title_node.text else orgunit_root.attrib["identifier"],
        "keyword": keyword_node.text if keyword_node is not None and keyword_node.text else (title_node.text if title_node is not None and title_node.text else orgunit_root.attrib["identifier"]),
    }


def merge_context(
    contract: dict[str, Any],
    context_dir: Path | None = None,
    cli_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    context: dict[str, str] = {}
    if context_dir is not None:
        context.update(load_context_from_dir(context_dir))

    json_orgunit = contract.get("package", {}).get("orgunit", {})
    if isinstance(json_orgunit, dict):
        mapping = {
            "identifier": json_orgunit.get("identifier"),
            "default_nav": json_orgunit.get("default_nav"),
            "default_homepage": json_orgunit.get("default_homepage"),
            "title": json_orgunit.get("title"),
            "keyword": json_orgunit.get("keyword"),
        }
        context.update({key: str(value) for key, value in mapping.items() if value})

    if cli_overrides:
        context.update({key: value for key, value in cli_overrides.items() if value})

    required = ["identifier", "default_nav", "default_homepage", "title", "keyword"]
    missing = [key for key in required if not context.get(key)]
    if missing:
        raise ValueError(
            "Missing course context fields: "
            + ", ".join(missing)
            + ". Provide --context-dir or explicit context fields."
        )
    return context


def add_empty_text_node(parent: ET.Element, tag: str, text_type: str) -> ET.Element:
    node = ET.SubElement(parent, tag, {"text_type": text_type})
    ET.SubElement(node, "text").text = ""
    return node


def build_rubrics_xml(contract: dict[str, Any]) -> ET.Element:
    root = ET.Element("rubrics", {"schemaversion": "v2011"})
    package = contract["package"]
    rubric_id_start = int(package.get("rubric_id_start", 1))
    resource_code_start = int(package.get("resource_code_start", 980001))
    level_id_base_start = int(package.get("level_id_base_start", 660000))
    resource_prefix = str(package.get("resource_prefix"))

    for offset, rubric in enumerate(contract["rubrics"]):
        rubric_id = rubric_id_start + offset
        rubric_el = ET.SubElement(
            root,
            "rubric",
            {
                "id": str(rubric_id),
                "resource_code": f"{resource_prefix}-{resource_code_start + offset}",
                "name": rubric["name"],
                "type": "1",
                "scoring_method": "3",
                "display_levels_in_des_order": "True",
                "state": "0",
                "visibility": "0",
                "uses_overall_score": "True",
                "has_manual_alignment": "False",
                "score_visible_to_assessed_users": "True",
                "enabled_feedback_copy": "False",
                "usage_restrictions": "Competency,ePortfolio",
            },
        )
        add_empty_text_node(rubric_el, "description", "text")
        criteria_groups = ET.SubElement(rubric_el, "criteria_groups")
        criteria_group = ET.SubElement(criteria_groups, "criteria_group", {"name": "Criteria", "sort_order": "1"})
        level_set = ET.SubElement(criteria_group, "level_set")
        levels = ET.SubElement(level_set, "levels")

        level_ids: dict[str, str] = {}
        rubric_levels = rubric.get("levels") or DEFAULT_LEVELS
        level_stride = 100 if contract.get("schema") == "coursecraft.rubric_authoring/1" else 10
        base_level_id = level_id_base_start + ((offset + 1) * level_stride)
        for level_offset, level in enumerate(rubric_levels, start=1):
            level_name = str(level["name"])
            level_id = str(base_level_id + level_offset)
            level_ids[level_name] = level_id
            ET.SubElement(
                levels,
                "level",
                {
                    "name": level_name,
                    "sort_order": str(level.get("sort_order", level_offset)),
                    "level_id": level_id,
                },
            )

        criteria_el = ET.SubElement(criteria_group, "criteria")
        for criterion_index, criterion in enumerate(rubric["criteria"], start=1):
            criterion_el = ET.SubElement(
                criteria_el,
                "criterion",
                {
                    "name": criterion["name"],
                    "sort_order": str(1 + (criterion_index - 1) * 10),
                },
            )
            cells = ET.SubElement(criterion_el, "cells")
            descriptions = criterion.get("descriptions", criterion.get("levels", {}))
            for level in rubric_levels:
                level_name = str(level["name"])
                multiplier = float(level["multiplier"])
                cell = ET.SubElement(
                    cells,
                    "cell",
                    {
                        "level_id": level_ids[level_name],
                        "cell_value": f"{criterion['weight'] * multiplier:.9f}",
                    },
                )
                description = ET.SubElement(cell, "description", {"text_type": "text/html"})
                ET.SubElement(description, "text").text = descriptions[level_name]
                add_empty_text_node(cell, "feedback", "text")

        overall_level_set = ET.SubElement(rubric_el, "overall_level_set")
        overall_levels = ET.SubElement(overall_level_set, "overall_levels")
        for overall_level_data in rubric["overall_levels"]:
            overall_level = ET.SubElement(
                overall_levels,
                "overall_level",
                {
                    "name": overall_level_data["name"],
                    "sort_order": str(overall_level_data["sort_order"]),
                    "range_start_value": _format_score_value(
                        float(overall_level_data["range_start_value"])
                    ),
                },
            )
            add_empty_text_node(overall_level, "description", "text")
            add_empty_text_node(overall_level, "feedback", "text")

    return root


def build_manifest_xml(context: dict[str, str], contract: dict[str, Any]) -> ET.Element:
    ET.register_namespace("", IMS_NS)
    ET.register_namespace("d2l_2p0", D2L_NS)
    ET.register_namespace("scorm_1p2", SCORM_NS)
    ET.register_namespace("imsmd", IMSMD_NS)

    manifest = ET.Element(f"{{{IMS_NS}}}manifest", {"identifier": contract["package"]["manifest_identifier"]})
    metadata = ET.SubElement(manifest, f"{{{IMS_NS}}}metadata")
    lom = ET.SubElement(metadata, f"{{{IMSMD_NS}}}lom")
    general = ET.SubElement(lom, f"{{{IMSMD_NS}}}general")
    title = ET.SubElement(general, f"{{{IMSMD_NS}}}title")
    ET.SubElement(
        title,
        f"{{{IMSMD_NS}}}langstring",
        {"{http://www.w3.org/XML/1998/namespace}lang": "en-us"},
    ).text = context["title"]
    keyword = ET.SubElement(general, f"{{{IMSMD_NS}}}keyword")
    ET.SubElement(
        keyword,
        f"{{{IMSMD_NS}}}langstring",
        {"{http://www.w3.org/XML/1998/namespace}lang": "en-us"},
    ).text = context["keyword"]
    ET.SubElement(general, f"{{{IMSMD_NS}}}language").text = "en-us"

    resources = ET.SubElement(manifest, f"{{{IMS_NS}}}resources")
    ET.SubElement(
        resources,
        f"{{{IMS_NS}}}resource",
        {
            "identifier": context["identifier"],
            "type": "webcontent",
            f"{{{D2L_NS}}}material_type": "orgunitconfig",
            f"{{{D2L_NS}}}link_target": "",
            "href": r"orgunitconfig\orgunitconfig.xml",
            "title": "",
        },
    )
    ET.SubElement(
        resources,
        f"{{{IMS_NS}}}resource",
        {
            "identifier": "res_rubrics",
            "type": "webcontent",
            f"{{{D2L_NS}}}material_type": "d2lrubrics",
            f"{{{D2L_NS}}}link_target": "",
            "href": "rubrics_d2l.xml",
            "title": "",
        },
    )
    return manifest


def build_orgunit_xml(context: dict[str, str]) -> ET.Element:
    return ET.Element(
        "orgunit",
        {
            "identifier": context["identifier"],
            "default_nav": context["default_nav"],
            "default_homepage": context["default_homepage"],
        },
    )


def write_xml(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass
    tree.write(path, encoding="utf-8", xml_declaration=True)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def assert_safe_replace_target(
    output_dir: Path,
    *,
    protected_sources: tuple[Path, ...] = (),
) -> Path:
    """Fail closed before recursively replacing a caller-selected directory."""

    raw_output = output_dir.expanduser()
    for candidate in (raw_output, *raw_output.parents):
        if candidate.exists() and candidate.is_symlink():
            raise ValueError("Refusing a symlinked output path.")
    resolved = raw_output.resolve(strict=False)
    repo_root = Path(__file__).resolve().parents[1]
    protected_roots = {
        Path("/").resolve(),
        Path("/tmp").resolve(),
        Path("/private/tmp").resolve(),
        Path(tempfile.gettempdir()).resolve(),
        repo_root,
        repo_root.parent.resolve(),
        Path.cwd().resolve(),
        Path.home().resolve(),
        Path.home().parent.resolve(),
    }
    if resolved in protected_roots:
        raise ValueError("Refusing a protected output anchor; choose a dedicated leaf directory.")
    for source_path in protected_sources:
        source = source_path.expanduser().resolve()
        if source == resolved or source.is_relative_to(resolved):
            raise ValueError(
                "Refusing output target because it contains an input or context source."
            )
    return resolved


def build_mapping_markdown(contract: dict[str, Any]) -> str:
    lines = [
        "# Rubric Mapping",
        "",
        "This package intentionally contains only rubric objects.",
        "",
        "Manual attachment in Brightspace is still required unless activity XML is also updated elsewhere.",
        "",
        "| Rubric Name | Activity Type | Source Title | Source ID | Grade Item ID |",
        "| --- | --- | --- | --- | --- |",
    ]
    for rubric in contract["rubrics"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    rubric["name"],
                    rubric.get("kind", ""),
                    rubric.get("source_title", ""),
                    rubric.get("source_id", ""),
                    rubric.get("grade_item_id", ""),
                ]
            )
            + " |"
        )

    notes = [str(note).strip() for note in contract.get("notes", []) if str(note).strip()]
    excluded = [str(item).strip() for item in contract.get("excluded_items", []) if str(item).strip()]

    if notes:
        lines.extend(["", "Notes:", ""])
        lines.extend([f"- {note}" for note in notes])
    if excluded:
        lines.extend(["", "Excluded items:", ""])
        lines.extend([f"- {item}" for item in excluded])
    return "\n".join(lines) + "\n"


def zip_package(package_dir: Path, zip_path: Path) -> None:
    """Write a byte-stable rubric package archive.

    The fixed timestamp and permissions are part of the portable producer
    contract.  Callers remain responsible for constraining package members.
    """
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as zf:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                arcname = path.relative_to(package_dir).as_posix()
                info = ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                zf.writestr(info, path.read_bytes())


def build_package(
    input_path: Path,
    output_dir: Path,
    context_dir: Path | None = None,
    cli_overrides: dict[str, str] | None = None,
    force: bool = False,
) -> dict[str, Path]:
    protected_sources = (input_path,) + ((context_dir,) if context_dir is not None else ())
    output_dir = assert_safe_replace_target(
        output_dir,
        protected_sources=protected_sources,
    )
    if output_dir.exists():
        if not force:
            raise ValueError(f"Output directory already exists: {output_dir}. Re-run with --force to replace it.")
        shutil.rmtree(output_dir)

    contract = normalize_contract(load_rubric_contract(input_path))
    context = merge_context(contract, context_dir=context_dir, cli_overrides=cli_overrides)

    package_dir = output_dir / "package"
    write_xml(package_dir / "rubrics_d2l.xml", build_rubrics_xml(contract))
    write_xml(package_dir / "imsmanifest.xml", build_manifest_xml(context, contract))
    write_xml(package_dir / "orgunitconfig" / "orgunitconfig.xml", build_orgunit_xml(context))
    write_json(output_dir / "normalized_rubrics.json", contract)
    (output_dir / "rubric_mapping.md").write_text(build_mapping_markdown(contract), encoding="utf-8")
    zip_package(package_dir, output_dir / "package.zip")

    return {
        "output_dir": output_dir,
        "package_dir": package_dir,
        "zip_path": output_dir / "package.zip",
        "mapping_path": output_dir / "rubric_mapping.md",
        "normalized_json_path": output_dir / "normalized_rubrics.json",
    }


def validate_package_dir(package_dir: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    summary: dict[str, Any] = {}
    expected_members = {
        "imsmanifest.xml",
        "orgunitconfig/orgunitconfig.xml",
        "rubrics_d2l.xml",
    }
    actual_members: set[str] = set()
    for path in package_dir.rglob("*"):
        relative = path.relative_to(package_dir).as_posix()
        if path.is_symlink():
            errors.append("Rubric-only package contains a symlink member.")
            continue
        if path.is_file():
            actual_members.add(relative)
            if path.stat().st_size > 10 * 1024 * 1024:
                errors.append("Rubric-only package member exceeds the 10 MiB safety limit.")
    unexpected_members = sorted(actual_members - expected_members)
    if unexpected_members:
        errors.append(
            f"Rubric-only package contains {len(unexpected_members)} unexpected member(s)."
        )

    manifest_path = package_dir / "imsmanifest.xml"
    orgunit_path = package_dir / "orgunitconfig" / "orgunitconfig.xml"
    rubrics_path = package_dir / "rubrics_d2l.xml"

    for path in [manifest_path, orgunit_path, rubrics_path]:
        if not path.exists():
            errors.append(f"Missing required file: {path.relative_to(package_dir)}")

    if errors:
        return errors, warnings, summary

    try:
        manifest_root = ET.parse(manifest_path).getroot()
        orgunit_root = ET.parse(orgunit_path).getroot()
        rubrics_root = ET.parse(rubrics_path).getroot()
    except (ET.ParseError, OSError):
        errors.append("Rubric-only package contains malformed XML.")
        return errors, warnings, summary
    if manifest_root.tag != f"{{{IMS_NS}}}manifest":
        errors.append("imsmanifest.xml root does not use the canonical manifest namespace.")

    direct_children = list(manifest_root)
    if any(
        _local_name(element.tag) in {"organizations", "organization"}
        for element in manifest_root.iter()
    ):
        errors.append("Manifest contains an unexpected organizations declaration.")
    if any(
        child.tag
        not in {
            f"{{{IMS_NS}}}metadata",
            f"{{{IMS_NS}}}resources",
        }
        for child in direct_children
    ):
        errors.append("Manifest contains unexpected top-level declarations.")
    resource_containers = [
        child for child in direct_children if child.tag == f"{{{IMS_NS}}}resources"
    ]
    resources: list[ET.Element] = []
    if len(resource_containers) != 1:
        errors.append("Manifest must contain exactly one canonical resources container.")
    else:
        if any(
            child.tag != f"{{{IMS_NS}}}resource"
            for child in list(resource_containers[0])
        ):
            errors.append("Manifest resources container has unexpected children.")
        resources = [
            child
            for child in list(resource_containers[0])
            if child.tag == f"{{{IMS_NS}}}resource"
        ]

    orgunit_identifier_from_manifest = None
    material_key = f"{{{D2L_NS}}}material_type"
    link_target_key = f"{{{D2L_NS}}}link_target"
    expected_attribute_keys = {
        "identifier",
        "type",
        "href",
        "title",
        material_key,
        link_target_key,
    }
    identifiers = [resource.attrib.get("identifier", "") for resource in resources]
    if len(resources) != 2:
        errors.append("Manifest must register exactly two rubric-only resources.")
    if (
        any(not identifier for identifier in identifiers)
        or len(set(identifiers)) != len(identifiers)
    ):
        errors.append("Manifest resource identifiers must be non-empty and unique.")
    if any(list(resource) for resource in resources):
        errors.append("Manifest resources must not contain dependencies or child declarations.")

    orgunit_resources = [
        resource
        for resource in resources
        if resource.attrib.get(material_key) == "orgunitconfig"
    ]
    rubric_resources = [
        resource
        for resource in resources
        if resource.attrib.get(material_key) == "d2lrubrics"
    ]
    if len(orgunit_resources) != 1:
        errors.append("Manifest must contain exactly one orgunitconfig resource.")
    if len(rubric_resources) != 1:
        errors.append("Manifest must contain exactly one d2lrubrics resource.")

    if len(orgunit_resources) == 1:
        orgunit_resource = orgunit_resources[0]
        orgunit_identifier_from_manifest = orgunit_resource.attrib.get("identifier")
        if (
            set(orgunit_resource.attrib) != expected_attribute_keys
            or orgunit_resource.attrib.get("type") != "webcontent"
            or orgunit_resource.attrib.get("href")
            != r"orgunitconfig\orgunitconfig.xml"
            or orgunit_resource.attrib.get(link_target_key) != ""
            or orgunit_resource.attrib.get("title") != ""
            or orgunit_identifier_from_manifest == "res_rubrics"
        ):
            errors.append("Manifest orgunitconfig resource is not canonical.")
    if len(rubric_resources) == 1:
        rubric_resource = rubric_resources[0]
        if (
            set(rubric_resource.attrib) != expected_attribute_keys
            or rubric_resource.attrib.get("identifier") != "res_rubrics"
            or rubric_resource.attrib.get("type") != "webcontent"
            or rubric_resource.attrib.get("href") != "rubrics_d2l.xml"
            or rubric_resource.attrib.get(link_target_key) != ""
            or rubric_resource.attrib.get("title") != ""
        ):
            errors.append("Manifest d2lrubrics resource is not canonical.")
    if any(
        resource not in orgunit_resources + rubric_resources
        for resource in resources
    ):
        errors.append("Manifest contains an unsupported resource material type.")

    if _local_name(orgunit_root.tag) != "orgunit":
        errors.append("orgunitconfig.xml root is not 'orgunit'.")
    if orgunit_identifier_from_manifest and orgunit_root.attrib.get("identifier") != orgunit_identifier_from_manifest:
        errors.append("Manifest orgunit identifier does not match orgunitconfig.xml identifier.")

    if _local_name(rubrics_root.tag) != "rubrics":
        errors.append("rubrics_d2l.xml root is not 'rubrics'.")
    if rubrics_root.attrib.get("schemaversion") != "v2011":
        errors.append("rubrics_d2l.xml does not declare schemaversion='v2011'.")

    rubric_elements = rubrics_root.findall("./rubric")
    summary["rubric_count"] = len(rubric_elements)
    if not rubric_elements:
        errors.append("rubrics_d2l.xml contains no rubric elements.")

    for rubric_index, rubric_el in enumerate(rubric_elements, start=1):
        if rubric_el.attrib.get("scoring_method") != "3":
            errors.append(f"Rubric {rubric_index} scoring_method is not '3'.")
        if rubric_el.attrib.get("uses_overall_score") != "True":
            errors.append(
                f"Rubric {rubric_index} does not enable uses_overall_score='True'."
            )

        level_elements = rubric_el.findall("./criteria_groups/criteria_group/level_set/levels/level")
        if len(level_elements) < 2:
            errors.append(
                f"Rubric {rubric_index} must contain at least two performance levels."
            )
            continue
        level_ids = [level.attrib.get("level_id", "") for level in level_elements]
        level_names = [level.attrib.get("name", "") for level in level_elements]
        if any(not value for value in level_ids):
            errors.append(f"Rubric {rubric_index} has a level missing level_id.")
        if len(set(level_ids)) != len(level_ids):
            errors.append(f"Rubric {rubric_index} has duplicate level_id values.")
        if any(not value for value in level_names):
            errors.append(f"Rubric {rubric_index} has a level missing name.")
        if len(set(level_names)) != len(level_names):
            errors.append(f"Rubric {rubric_index} has duplicate level names.")

        criteria = rubric_el.findall("./criteria_groups/criteria_group/criteria/criterion")
        if not criteria:
            errors.append(f"Rubric {rubric_index} contains no criteria.")
            continue

        highest_total = 0.0
        for criterion_index, criterion in enumerate(criteria, start=1):
            cells = criterion.findall("./cells/cell")
            if len(cells) != len(level_elements):
                errors.append(
                    f"Criterion {criterion_index} in rubric {rubric_index} has "
                    f"{len(cells)} cells but the rubric defines {len(level_elements)} levels."
                )
                continue
            cell_level_ids = [cell.attrib.get("level_id", "") for cell in cells]
            if (
                len(set(cell_level_ids)) != len(cell_level_ids)
                or set(cell_level_ids) != set(level_ids)
            ):
                errors.append(
                    f"Criterion {criterion_index} in rubric {rubric_index} "
                    "does not map exactly once to every level."
                )
                continue
            values: list[float] = []
            for cell in cells:
                level_id = cell.attrib.get("level_id", "")
                cell_value = cell.attrib.get("cell_value", "")
                if not level_id or not cell_value:
                    errors.append(
                        f"Criterion {criterion_index} in rubric {rubric_index} "
                        "has a cell missing level_id or cell_value."
                    )
                if level_id and level_id not in level_ids:
                    errors.append(
                        f"Criterion {criterion_index} in rubric {rubric_index} "
                        "has a cell pointing to an unknown level_id."
                    )
                try:
                    values.append(float(cell_value))
                except ValueError:
                    errors.append(
                        f"Criterion {criterion_index} in rubric {rubric_index} "
                        "has a non-numeric cell_value."
                    )
            if values:
                highest_total += max(values)

        if highest_total <= 0:
            errors.append(
                f"Rubric {rubric_index} has no positive cell-score total."
            )
        if highest_total > 100.0 + 1e-6:
            errors.append(
                f"Rubric {rubric_index} highest cell-score total exceeds 100."
            )

        overall_levels = rubric_el.findall("./overall_level_set/overall_levels/overall_level")
        if len(overall_levels) != len(level_elements):
            errors.append(
                f"Rubric {rubric_index} overall score table has {len(overall_levels)} levels "
                f"but the rubric defines {len(level_elements)} levels."
            )
            continue

        threshold_map: dict[str, float] = {}
        expected_sort_orders = {
            level.attrib.get("name", ""): level.attrib.get("sort_order", "")
            for level in level_elements
        }
        for overall_level in overall_levels:
            level_name = overall_level.attrib.get("name", "")
            if level_name not in expected_sort_orders:
                errors.append(
                    f"Rubric {rubric_index} has an unexpected overall level name."
                )
                continue
            if level_name in threshold_map:
                errors.append(
                    f"Rubric {rubric_index} defines an overall level more than once."
                )
                continue
            sort_order = overall_level.attrib.get("sort_order", "")
            if sort_order != expected_sort_orders[level_name]:
                errors.append(
                    f"Rubric {rubric_index} has an overall level with an incorrect sort_order."
                )
            try:
                threshold_map[level_name] = float(overall_level.attrib.get("range_start_value", ""))
            except ValueError:
                errors.append(
                    f"Rubric {rubric_index} has an overall level with a non-numeric range_start_value."
                )

        missing_levels = [level_name for level_name in level_names if level_name not in threshold_map]
        if missing_levels:
            errors.append(
                f"Rubric {rubric_index} overall score table is missing "
                f"{len(missing_levels)} level(s)."
            )
            continue

        ordered_thresholds = sorted(threshold_map.values())
        if abs(ordered_thresholds[0]) > 1e-9:
            errors.append(
                f"Rubric {rubric_index} lowest overall threshold must start at 0."
            )
        if any(threshold < 0 or threshold > 100 for threshold in ordered_thresholds):
            errors.append(
                f"Rubric {rubric_index} overall thresholds must stay within the 0-100 score range."
            )
        if any(later <= earlier for earlier, later in zip(ordered_thresholds, ordered_thresholds[1:])):
            errors.append(
                f"Rubric {rubric_index} overall thresholds must increase from the lowest-scoring level "
                "to the highest-scoring level."
            )

    return errors, warnings, summary


def validate_package_path(path: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    if path.is_dir():
        return validate_package_dir(path)
    if path.is_file() and path.suffix.lower() == ".zip":
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                temp_root = Path(tmp_dir)
                with ZipFile(path) as zf:
                    if any(info.flag_bits & 0x1 for info in zf.infolist()):
                        return ["Archive contains encrypted members."], [], {}
                    expected = {
                        "imsmanifest.xml",
                        "orgunitconfig/orgunitconfig.xml",
                        "rubrics_d2l.xml",
                    }
                    names = [info.filename for info in zf.infolist()]
                    errors: list[str] = []
                    if len(names) != len(set(names)):
                        errors.append("Archive contains duplicate member names.")
                    for member_index, info in enumerate(zf.infolist(), start=1):
                        member = info.filename.replace("\\", "/")
                        parts = Path(member).parts
                        mode = (info.external_attr >> 16) & 0o170000
                        if member.startswith("/") or ".." in parts:
                            errors.append(f"Archive member {member_index} is unsafe.")
                        if mode == 0o120000:
                            errors.append(f"Archive member {member_index} is a symlink.")
                        if info.file_size > 10 * 1024 * 1024:
                            errors.append(
                                f"Archive member {member_index} exceeds the 10 MiB safety limit."
                            )
                        if member not in expected:
                            errors.append(
                                f"Archive member {member_index} is unexpected."
                            )
                    missing = sorted(expected - set(names))
                    if missing:
                        errors.append(f"Archive is missing required members: {', '.join(missing)}.")
                    if errors:
                        return errors, [], {}
                    for info in zf.infolist():
                        destination = temp_root / info.filename
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(zf.read(info))
                return validate_package_dir(temp_root)
        except (BadZipFile, OSError, RuntimeError):
            return ["Archive is unreadable, malformed, or encrypted."], [], {}
    raise ValueError("Expected a package directory or .zip file.")
