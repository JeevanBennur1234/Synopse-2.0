"""Isolated subprocess worker for executing a single document analysis job."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
import sys

import cv2

from app.adapters.gst_registry import check_registry
from app.explainability import explain
from app.pipeline.orchestrator import execute
from app.preprocessing.document import process
from app.preprocessing.fields import locate
from app.preprocessing.tables import extract_tables
from app.scoring.risk import evaluate
from app.preprocessing.profiles import classify, coverage, PROFILES


def run_pipeline(job_id: str, source: Path) -> dict:
    """Execute document preprocessing, forensic detectors, scoring, and explanation."""
    # Detector-level parallelism owns the CPU concurrency in this worker.
    cv2.setNumThreads(1)
    pages, fields, warnings = process(source)
    for page in pages:
        page["preview_url"] = f"/result/{job_id}/pages/{page['page']}"
    locations = locate(pages, fields)
    context = dict(fields, _pages=pages, _field_locations=locations)
    tables, table_warnings = extract_tables(pages)
    context.update(tables)
    warnings.extend(table_warnings)

    kind, type_confidence = classify(pages, fields, tables)
    context["_document_type"] = kind
    findings, runs, detector_warnings = execute(source, pages, context)
    core_checks = PROFILES[kind]
    risk, risk_meta = evaluate(runs, core_checks)
    profile = coverage(kind, findings)
    reasons = []
    if any("low OCR confidence" in w or "no readable text" in w for w in warnings):
        reasons.append("Image quality or OCR confidence limits verification.")
    if kind != "invoice" and (profile["verified"] < 2 or profile["verified"] < profile["required"]):
        reasons.append("Too few applicable business checks could be verified.")
    if kind != "invoice" and reasons and risk["risk_level"] == "low":
        risk.update(risk_score=None, risk_level="inconclusive")
    missing_core = risk["risk_level"] == "inconclusive" and kind == "invoice"

    result: dict = {}
    result.update(**risk)
    result.update(document_type=kind, document_type_confidence=type_confidence,
                  profile_coverage=profile, limited_evidence=bool(reasons),
                  limited_evidence_reasons=reasons,
                  verdict="Limited checks" if reasons and risk["risk_level"] == "inconclusive" and kind != "invoice" else
                  ("Insufficient evidence" if risk["risk_level"] == "inconclusive" else risk["risk_level"].title()))
    result["insufficient_core_evidence"] = missing_core
    result["review_required"] = (
        any(f.status == "suspicious" or (
            f.status == "inconclusive" and f.evidence.startswith("Possible mismatch, verify manually")
        ) for f in findings) or risk["risk_level"] == "inconclusive"
    )
    result["check_status_counts"] = {
        status: sum(f.status == status for f in findings)
        for status in ("passed", "suspicious", "inconclusive", "not_applicable", "error")
    }
    all_warnings = warnings + detector_warnings + (
        ["Insufficient conclusive evidence for overall risk."] if risk["risk_score"] is None else []
    )
    result.update(
        status="completed",
        pages=pages,
        fields=fields,
        field_locations=locations,
        findings=[f.model_dump() for f in findings],
        engine_runs=runs,
        warnings=all_warnings,
    )

    try:
        result["registry_checks"] = [r.model_dump() for r in check_registry(fields, locations)]
    except Exception:
        logging.exception("Mock registry lookup failed")
        result["warnings"].append("Mock registry lookup unavailable.")

    try:
        result["explanation"] = explain(
            risk,
            findings,
            runs,
            result["warnings"],
            floor_applied=risk_meta["floor_applied"],
            other_checks_clean=risk_meta["other_checks_clean"],
        ).model_dump()
    except Exception:
        logging.exception("Explanation generation failed")
        result["warnings"].append("Explanation unavailable.")

    return result


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 3:
        sys.stderr.write("Usage: python -m app.job_worker <job_id> <source_path> <output_json>\n")
        return 2

    job_id, source_arg, output_arg = args
    source = Path(source_arg)
    output_path = Path(output_arg)
    try:
        payload = run_pipeline(job_id, source)
        output_path.write_text(json.dumps(payload), encoding="utf-8")
        return 0
    except Exception:
        logging.exception("Processing failed for job %s", job_id)
        failure_payload = {"status": "failed", "warnings": ["Document processing failed."]}
        output_path.write_text(json.dumps(failure_payload), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
