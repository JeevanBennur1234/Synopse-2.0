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

    findings, runs, detector_warnings = execute(source, pages, context)
    is_invoice = not tables.get("_bank_transactions") and bool(
        fields.get("invoice_number") or fields.get("invoice_date")
        or (fields.get("subtotal") and fields.get("total"))
        or any(re.search(r"\binvoice\b", " ".join(p["text"].splitlines()[:6]), re.I)
               for p in pages)
    )
    core_checks = (
        "invoice_arithmetic_consistency", "invoice_line_items_arithmetic", "tax_rate_arithmetic"
    ) if is_invoice else ()
    risk, risk_meta = evaluate(runs, core_checks)
    missing_core = risk["risk_level"] == "inconclusive" and bool(core_checks) and risk["coverage"] < 1


    result: dict = {}
    result.update(**risk)
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
