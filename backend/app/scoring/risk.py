"""Provisional screening heuristic, not a calibrated fraud probability."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

WEIGHTS = {"visual": 0.30, "file_forensics": 0.20, "consistency": 0.50}
MIN_COVERAGE = 0.60
MIN_CONFIDENCE = 0.50
STRONG_SCORE_THRESHOLD = 0.40

LEVEL_ORDER = {"inconclusive": 0, "low": 1, "medium": 2, "high": 3}

# Structural evidence independence groups (prevents correlated signals from stacking).
EVIDENCE_GROUPS: dict[str, str] = {
    "ela": "visual_pixel",
    "noise_inconsistency": "visual_pixel",
    "copy_move": "visual_clone",
    "image_metadata": "container_metadata",
    "pdf_metadata_integrity": "container_metadata",
    "pdf_structural_integrity": "pdf_structure",
    "gstin_validation": "identifier_validation",
    "ifsc_validation": "identifier_validation",
    "invoice_arithmetic_consistency": "financial_arithmetic",
    "invoice_line_items_arithmetic": "financial_arithmetic",
    "cgst_sgst_symmetry": "financial_arithmetic",
    "gst_jurisdiction_consistency": "financial_arithmetic",
    "tax_rate_arithmetic": "financial_arithmetic",
    "bank_statement_balance_consistency": "financial_arithmetic",
    "calendar_date_validity": "temporal",
    "date_chronology": "temporal",
    "qr_code_consistency": "qr_cross_check",
}

# Only rules with reliable failure evidence can establish a structural floor.
FLOOR_ELIGIBLE_RULES = frozenset({
    "pdf_structural_integrity", "gstin_validation", "ifsc_validation",
    "invoice_arithmetic_consistency", "invoice_line_items_arithmetic",
    "cgst_sgst_symmetry", "gst_jurisdiction_consistency", "tax_rate_arithmetic",
    "bank_statement_balance_consistency", "calendar_date_validity", "date_chronology",
})
COPY_MOVE_MIN_FLOOR_CONFIDENCE = 0.70

# An isolated ELA signal also retains its existing weighted risk cap.
LOW_CONFIDENCE_DETECTORS = frozenset({"ela"})


def _evidence_group(finding: dict[str, Any], engine_name: str) -> str:
    det_name = str(finding.get("name") or "").strip().lower()
    if det_name in EVIDENCE_GROUPS:
        return EVIDENCE_GROUPS[det_name]
    if det_name:
        return f"detector:{det_name}"
    return f"engine:{engine_name}"


def _classify_severity(finding: dict[str, Any]) -> str:
    if finding.get("status") != "suspicious":
        return "info"
    det_name = str(finding.get("name") or "").strip().lower()
    conf = float(finding.get("confidence") or 0.0)
    score = float(finding.get("score") or 0.0)
    # Suspicious copy-move output requires both texture and RANSAC gates in the detector.
    eligible = det_name in FLOOR_ELIGIBLE_RULES or (
        det_name == "copy_move" and conf >= COPY_MOVE_MIN_FLOOR_CONFIDENCE
    )
    if not eligible:
        return "suspicious"
    if conf >= MIN_CONFIDENCE and score >= STRONG_SCORE_THRESHOLD:
        return "strong"
    return "suspicious"


def _score_to_level(score: float) -> str:
    if score >= 70:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def evaluate(runs: list[dict[str, Any]], core_checks: tuple[str, ...] = ()) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compute heuristic risk score, structural risk-level floor, and finding annotations."""
    scores: dict[str, float] = {}
    excluded = {
        r["engine"]
        for r in runs
        if r["status"] == "not_applicable"
        and r.get("findings")
        and all(f["status"] == "not_applicable" for f in r["findings"])
    }
    applicable = sum(v for k, v in WEIGHTS.items() if k not in excluded)

    suspicious_groups: set[str] = set()
    strong_groups: set[str] = set()
    suspicious_detectors: set[str] = set()
    has_passed = False

    annotated_runs = deepcopy(runs)
    for run in annotated_runs:
        engine_name = run["engine"]
        for finding in run.get("findings", []):
            status = finding.get("status")
            if status == "passed":
                has_passed = True
            elif status == "suspicious":
                det_name = str(finding.get("name") or "").strip().lower()
                if det_name:
                    suspicious_detectors.add(det_name)
                grp = _evidence_group(finding, engine_name)
                if float(finding.get("confidence") or 0.0) >= MIN_CONFIDENCE:
                    suspicious_groups.add(grp)
                sev = _classify_severity(finding)
                finding["severity"] = sev
                if sev == "strong":
                    strong_groups.add(grp)
            if status != "suspicious":
                finding["severity"] = "info"

    for run in annotated_runs:
        engine_name = run["engine"]
        for finding in run.get("findings", []):
            if finding.get("status") == "suspicious":
                grp = _evidence_group(finding, engine_name)
                finding["corroborated"] = len(suspicious_groups - {grp}) > 0
            else:
                finding["corroborated"] = False

        if engine_name not in WEIGHTS or run["status"] != "completed":
            continue
        usable = [
            f
            for f in run.get("findings", [])
            if f["status"] in ("passed", "suspicious") and f["confidence"] >= MIN_CONFIDENCE
        ]
        if usable:
            scores[engine_name] = max(f["score"] for f in usable)

    observed = sum(WEIGHTS[k] for k in scores)
    coverage = observed / applicable if applicable else 0.0
    core = {
        f["name"]: f["status"]
        for run in annotated_runs for f in run.get("findings", [])
        if f.get("name") in core_checks
    }
    required = [name for name in core_checks if core.get(name) != "not_applicable"]
    missing_core = any(core.get(name) not in ("passed", "suspicious") for name in required)
    if required:
        coverage = sum(core.get(name) in ("passed", "suspicious") for name in required) / len(required)


    # Determine structural floor from non-inconclusive strong findings.
    if len(strong_groups) >= 2:
        floor_level = "high"
    elif len(strong_groups) == 1:
        floor_level = "medium"
    else:
        floor_level = "low"

    ela_only = bool(suspicious_detectors) and suspicious_detectors <= LOW_CONFIDENCE_DETECTORS

    if (missing_core and not suspicious_detectors) or (
        not core_checks and coverage < MIN_COVERAGE
    ) or not observed:
        risk = dict(risk_score=None, risk_level="inconclusive", coverage=round(coverage, 4))
        meta = dict(
            floor_applied=False,
            floor_level=floor_level,
            weighted_level="inconclusive",
            other_checks_clean=has_passed,
            strong_group_count=len(strong_groups),
            annotated_runs=annotated_runs,
        )
        return risk, meta

    score = round(100 * sum(WEIGHTS[k] * v for k, v in scores.items()) / observed, 2)
    weighted_level = _score_to_level(score)

    # Partial analysis with no strong finding cannot establish low overall risk.
    if not core_checks and coverage < 0.999 and weighted_level == "low" and floor_level == "low":
        risk = dict(risk_score=None, risk_level="inconclusive", coverage=round(coverage, 4))
        meta = dict(
            floor_applied=False,
            floor_level=floor_level,
            weighted_level=weighted_level,
            other_checks_clean=has_passed,
            strong_group_count=len(strong_groups),
            annotated_runs=annotated_runs,
        )
        return risk, meta

    level = floor_level if LEVEL_ORDER[floor_level] > LEVEL_ORDER[weighted_level] else weighted_level
    if ela_only and level == "high":
        level = "medium"

    floor_applied = LEVEL_ORDER[level] > LEVEL_ORDER[weighted_level]
    risk = dict(
        risk_score=score if level != "inconclusive" else None,
        risk_level=level,
        coverage=round(coverage, 4),
    )
    meta = dict(
        floor_applied=floor_applied,
        floor_level=floor_level,
        weighted_level=weighted_level,
        other_checks_clean=has_passed,
        strong_group_count=len(strong_groups),
        annotated_runs=annotated_runs,
    )
    return risk, meta


def calculate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Return heuristic risk score, level, and coverage."""
    risk, _ = evaluate(runs)
    return risk
