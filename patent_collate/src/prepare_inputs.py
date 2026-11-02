#!/usr/bin/env python3
"""Prepare table XML/context pairs using the uploaded ScienceAid analyzer.

Install beside scienceaid_preprocess.py in patent_collate/src/.
This module does not call an LLM and does not modify Atlas2 extraction code.

Run from patent_collate/:
    python3 src/prepare_inputs.py --input-dir PATH --output-dir NEW_PATH --tables 20 40

The --tables values are display labels read from XML headings, NOT source
order or USPTO wrapper IDs. PDF appearance is not independently verified.
Only unambiguous positive integer labels are exported in this first version.
Duplicate/missing labels or empty context stop export; review table_mapping.csv.
An existing ScienceAid analysis JSON can be supplied with --analysis-json.

ScienceAid behavior is retained: <table> enumeration and up to five preceding
nonempty, non-table paragraphs. No context fallback and no LLM table selection.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

# Import only the preprocessing module, not Atlas2's API client.
if __package__:
    from .scienceaid_preprocess import PatentXMLAnalyzer
else:
    from scienceaid_preprocess import PatentXMLAnalyzer


PATENT_ID = re.compile(r"US\d{6,12}[A-Z]\d")
DISPLAY_LABEL = re.compile(
    r"^TABLE\s*([1-9]\d{0,4})\s*[.:]?\s*"
    r"(?:(?:[-\u2013\u2014]\s*)?\(?continued\)?\.?)?$", re.IGNORECASE
)
MAPPING_FIELDS = [
    "uspto_id", "scienceaid_table_id", "display_table", "display_label_text",
    "xml_wrapper_id", "source_file", "selected", "context_paragraph_count",
    "is_aso_candidate", "xml_file", "context_file", "status", "warning",
]


class PreparationError(ValueError):
    """Input cannot be safely converted; any diagnostics remain on disk."""


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1] if isinstance(element.tag, str) else ""


def _text(element: ET.Element) -> str:
    return " ".join(unicodedata.normalize("NFKC", "".join(element.itertext())).split())


def _validate_patent(value: Any) -> str:
    if not isinstance(value, str) or not PATENT_ID.fullmatch(value):
        raise PreparationError(f"Invalid USPTO identifier: {value!r}")
    return value


def read_display_label(table: ET.Element) -> tuple[int | None, str, str]:
    """Read conservative TABLE N headings, never guess an offset from order.

    A direct caption/title or the FIRST nonempty row must contain an exact
    TABLE N label (optionally 'continued'). We do not search ordinary data rows
    for references to other tables. Split cells such as TABLE | 40 are joined.
    Letter/Roman/range labels are intentionally not converted to an integer.
    """
    candidates: list[str] = []
    for child in table:
        if _tag(child) in {"caption", "title"}:
            text = _text(child)
            if text:
                candidates.append(text)
    for row in table.iter():
        if _tag(row) != "row":
            continue
        cells = [_text(cell) for cell in row if _tag(cell) == "entry"]
        text = " ".join(cell for cell in cells if cell).strip()
        if text:
            candidates.append(text)
            break
    labels = [(int(match.group(1)), text) for text in candidates
              if (match := DISPLAY_LABEL.fullmatch(text))]
    numbers = {number for number, _ in labels}
    if len(numbers) == 1:
        return labels[0][0], labels[0][1], ""
    if len(numbers) > 1:
        return None, " | ".join(candidates), "CONFLICTING_DISPLAY_LABELS"
    return None, " | ".join(candidates), "DISPLAY_LABEL_MISSING_OR_UNSUPPORTED"


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def _wrapper_ids(analyzer: PatentXMLAnalyzer, analysis: dict[str, Any]) -> dict[int, str]:
    """Recover real parent <tables id=...> values from the parsed full XML.

    JSON-only mode cannot recover these IDs; blanks remain unknown, not equal
    to scienceaid_table_id. No source XML is fetched from paths inside JSON.
    """
    root = analyzer.root
    tables = root.findall(".//table")
    if len(tables) != len(analysis["tables"]):
        raise PreparationError("Analyzer table count differs from parsed XML")
    parents = {child: parent for parent in root.iter() for child in parent}
    result: dict[int, str] = {}
    for order, table in enumerate(tables, 1):
        if analysis["tables"][order - 1]["table_id"] != order:
            raise PreparationError("Analyzer table ordering changed; check mapping")
        parent = parents.get(table)
        while parent is not None and _tag(parent) != "tables":
            parent = parents.get(parent)
        result[order] = parent.get("id", "") if parent is not None else ""
    return result


def _build_rows(analysis: dict[str, Any], source_file: str, wrapper_ids: dict[int, str],
                selected_labels: set[int] | None) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]], list[str]]:
    patent = _validate_patent(analysis.get("patent_number"))
    tables = analysis.get("tables")
    if not isinstance(tables, list) or not tables:
        raise PreparationError(f"{patent}: analysis has no tables")
    ids = [item.get("table_id") for item in tables if isinstance(item, dict)]
    if (len(ids) != len(tables) or any(type(idx) is not int or idx <= 0 for idx in ids)
            or len(ids) != len(set(ids))):
        raise PreparationError(f"{patent}: invalid/duplicate ScienceAid table IDs")
    rows: list[dict[str, Any]] = []
    payloads: list[tuple[str, str, str]] = []
    errors: list[str] = []
    parsed: list[tuple[dict[str, Any], str, list[str], int | None, str, str]] = []
    for item in tables:
        idx = item["table_id"]
        xml = item.get("table_xml")
        paras = item.get("preceding_paragraphs")
        if not isinstance(xml, str) or not xml.strip():
            raise PreparationError(f"{patent}, source {idx}: missing table_xml")
        try:
            table = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise PreparationError(f"{patent}, source {idx}: invalid table XML: {exc}") from exc
        if _tag(table) != "table":
            raise PreparationError(f"{patent}, source {idx}: root must be <table>")
        if not isinstance(paras, list) or any(not isinstance(p, str) for p in paras):
            raise PreparationError(f"{patent}, source {idx}: invalid preceding_paragraphs")
        number, label, warning = read_display_label(table)
        parsed.append((item, xml, paras, number, label, warning))
    counts = Counter(number for _, _, _, number, _, _ in parsed if number is not None)
    found = set(counts)
    if selected_labels is not None and (missing := selected_labels - found):
        errors.append(f"{patent}: requested display tables not found: {sorted(missing)}")
    for item, xml, paras, number, label, label_warning in parsed:
        idx = item["table_id"]
        selected = selected_labels is None or number in selected_labels
        context_parts = [p.strip() for p in paras if p.strip()]
        context = "\n\n".join(context_parts)
        issues = [label_warning] if label_warning else []
        if number is not None and counts[number] > 1:
            issues.append("DUPLICATE_DISPLAY_LABEL")
        if not context:
            issues.append("EMPTY_CONTEXT")
        blocking = bool(issues)
        warnings = issues.copy()
        if not wrapper_ids.get(idx):
            warnings.append("WRAPPER_ID_UNAVAILABLE")
        if 0 < len(context_parts) < 5:
            warnings.append("FEWER_THAN_FIVE_PARAGRAPHS")
        if selected and blocking:
            errors.append(f"{patent}, source {idx}, display {number}: {', '.join(issues)}")
        ready = selected and not blocking
        stem = f"{patent}_table_{number:05d}" if ready else ""
        rows.append({
            "uspto_id": patent,
            "scienceaid_table_id": idx,
            "display_table": number if number is not None else "",
            "display_label_text": label,
            "xml_wrapper_id": wrapper_ids.get(idx, ""),
            "source_file": source_file,
            "selected": "yes" if selected else "no",
            "context_paragraph_count": len(context_parts),
            "is_aso_candidate": item.get("is_aso_candidate", ""),
            "xml_file": f"atlas2_input/{stem}.xml" if ready else "",
            "context_file": f"atlas2_input/{stem}_context.txt" if ready else "",
            "status": "ready" if ready else ("blocked" if selected else "not_selected"),
            "warning": ";".join(warnings),
        })
        if ready:
            payloads.append((stem, xml.strip() + "\n", context + "\n"))
    return rows, payloads, errors


def prepare_inputs(*, input_dir: str | Path | None = None,
                   analysis_json: str | Path | None = None,
                   output_dir: str | Path,
                   tables: Iterable[int] | None = None,
                   verbose: bool = False) -> Path:
    """Create NEW output_dir and return its atlas2_input/ path after validation.

    Exactly one input source is required. input_dir is flat, accepts .xml/.XML,
    and must contain full patent documents, not pre-split tables/subdocuments.
    --tables applies the same display numbers to EACH input patent; missing
    requested labels are errors. No ASO/sequence filtering is applied.

    After validation errors, analysis/ and table_mapping.csv remain available.
    No atlas2_input/ is published unless the whole selected batch is valid.
    Existing output folders are never reused, deleted, or overwritten.
    """
    if (input_dir is None) == (analysis_json is None):
        raise PreparationError("Supply exactly one of input_dir or analysis_json")
    labels = set(tables) if tables is not None else None
    if labels is not None and (not labels or any(type(n) is not int or n <= 0 or n > 99999 for n in labels)):
        raise PreparationError("tables must contain positive integers from 1 to 99999")
    if input_dir is not None:
        directory = Path(input_dir).expanduser().resolve()
        if not directory.is_dir():
            raise FileNotFoundError(f"Input directory does not exist: {directory}")
        sources = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".xml")
        if not sources:
            raise PreparationError(f"No .xml/.XML files in: {directory}")
        for source in sources:
            if "_table_" in source.stem.lower() or re.search(r"-S\d+", source.stem, re.IGNORECASE):
                raise PreparationError(f"Expected full patent XML, not a table/subdocument: {source.name}")
            _validate_patent(source.stem.split("-")[0])
        patents = [p.stem.split("-")[0] for p in sources]
        if len(patents) != len(set(patents)):
            raise PreparationError("Multiple source files for one USPTO ID; keep one version per run")
    else:
        source = Path(analysis_json).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Analysis JSON does not exist: {source}")
        sources = [source]
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    analysis_dir = output / "analysis"
    analysis_dir.mkdir()
    rows: list[dict[str, Any]] = []
    payloads: list[tuple[str, str, str]] = []
    errors: list[str] = []
    try:
        for source in sources:
            if input_dir is not None:
                analyzer = PatentXMLAnalyzer(source, verbose=verbose)
                analysis = analyzer.process_patent(analysis_dir)
                if _tag(analyzer.root) in {"table", "tables"}:
                    raise PreparationError(f"Not a full patent XML: {source.name}")
                wrapper_ids = _wrapper_ids(analyzer, analysis)
            else:
                analysis = json.loads(source.read_text(encoding="utf-8-sig"))
                if not isinstance(analysis, dict):
                    raise PreparationError("Analysis JSON root must be an object")
                patent = _validate_patent(analysis.get("patent_number"))
                _write_json(analysis_dir / f"{patent}_analysis.json", analysis)
                wrapper_ids = {}
            patent_rows, patent_payloads, patent_errors = _build_rows(analysis, str(source), wrapper_ids, labels)
            rows.extend(patent_rows)
            payloads.extend(patent_payloads)
            errors.extend(patent_errors)
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        errors.append(str(exc))
    if not payloads and not errors:
        errors.append("No tables selected")
    stems = [stem for stem, _, _ in payloads]
    if len(stems) != len(set(stems)):
        errors.append("Duplicate output filenames")
    # A failed batch contains diagnostics only, never a partially valid input set.
    if errors:
        for row in rows:
            if row["status"] == "ready":
                row["status"] = "blocked_by_batch_error"
            row["xml_file"] = ""
            row["context_file"] = ""
    mapping_path = output / "table_mapping.csv"
    with mapping_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MAPPING_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    if errors:
        detail = "\n".join(errors)
        (output / "preparation_errors.txt").write_text(detail + "\n", encoding="utf-8")
        raise PreparationError(
            f"Preparation stopped. No atlas2_input directory was created.\n"
            f"{detail}\nReview {mapping_path} and analysis/. Use a new output directory for the next attempt."
        )
    staging = output / ".atlas2_input_building"
    staging.mkdir()
    for stem, xml, context in payloads:
        with (staging / f"{stem}.xml").open("x", encoding="utf-8") as stream:
            stream.write(xml)
        with (staging / f"{stem}_context.txt").open("x", encoding="utf-8") as stream:
            stream.write(context)
    target = output / "atlas2_input"
    staging.rename(target)
    for row in rows:
        if row["warning"]:
            print(f"NOTE: {row['uspto_id']} source {row['scienceaid_table_id']}: {row['warning']}")
    print(f"Prepared {len(payloads)} table XML/context pair(s). No LLM API was called.")
    print(f"Atlas2 input: {target}")
    print(f"Table mapping: {mapping_path}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-dir", type=Path, help="Flat folder containing full patent XML files")
    source.add_argument("--analysis-json", type=Path, help="Existing ScienceAid analysis JSON (wrapper IDs remain unknown)")
    parser.add_argument("--output-dir", type=Path, required=True, help="New output directory; must not already exist")
    parser.add_argument("--tables", type=int, nargs="+", help="Display table numbers, e.g. --tables 20 40; omitted: all")
    parser.add_argument("--verbose", action="store_true", help="Show ScienceAid analyzer messages")
    args = parser.parse_args()
    try:
        prepare_inputs(input_dir=args.input_dir, analysis_json=args.analysis_json,
                       output_dir=args.output_dir, tables=args.tables, verbose=args.verbose)
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
