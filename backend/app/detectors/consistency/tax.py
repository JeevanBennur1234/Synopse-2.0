"""Tax consistency validation detector.

Validates:
1. CGST and SGST symmetry for intra-state GST supplies (CGST == SGST).
2. IGST versus CGST/SGST mutually exclusive jurisdictional application.
3. Tax amounts against explicitly extracted tax rates and taxable values.
4. Absence of assumptions regarding fixed 18% rates or place of supply inferred purely from GSTIN.
5. Inconclusive handling when required context is missing.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from app.detectors.consistency.arithmetic import (
    DEFAULT_ROUNDING_TOLERANCE,
    LINE_ITEM_TOLERANCE,
    parse_decimal_candidate,
    resolve_candidate_field,
)
from app.schemas import BoundingBox, DetectorResult

STANDARD_GST_SLABS = (
    Decimal("0.0"),
    Decimal("0.25"),
    Decimal("3.0"),
    Decimal("5.0"),
    Decimal("12.0"),
    Decimal("18.0"),
    Decimal("28.0"),
)


def _parse_tax_rate(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    val_str = str(raw).strip()
    if not val_str:
        return None
    cleaned = re.sub(r"[^\d.]", "", val_str)
    if not cleaned:
        return None
    try:
        rate = Decimal(cleaned)
        # If passed as 0.18, convert to 18%
        if Decimal("0.0") < rate < Decimal("1.0"):
            rate = rate * Decimal("100")
        return rate
    except Exception:
        return None


def _extract_boxes(field_keys: list[str], fields: dict[str, Any]) -> list[BoundingBox]:
    boxes: list[BoundingBox] = []
    locations = fields.get("_field_locations")
    if isinstance(locations, dict):
        for k in field_keys:
            if k in locations:
                loc_data = locations[k]
                items = loc_data if isinstance(loc_data, list) else [loc_data]
                for item in items:
                    if isinstance(item, dict):
                        bbox = item.get("bbox") or item.get("box")
                        page_idx = item.get("page", 0)
                        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                            try:
                                x, y, w, h = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                                if w > 0 and h > 0 and x >= 0 and y >= 0 and page_idx >= 0:
                                    boxes.append(BoundingBox(page=page_idx, x=x, y=y, w=w, h=h))
                            except (ValueError, TypeError):
                                pass
    return boxes


def validate_tax_consistency(fields: dict[str, Any]) -> list[DetectorResult]:
    """Validates tax consistency across CGST, SGST, IGST, subtotal and explicit rates."""
    results: list[DetectorResult] = []

    cgst, cgst_cands, cgst_status = resolve_candidate_field("cgst", fields)
    sgst, sgst_cands, sgst_status = resolve_candidate_field("sgst", fields)
    igst, igst_cands, igst_status = resolve_candidate_field("igst", fields)
    subtotal, _, sub_status = resolve_candidate_field("subtotal", fields)

    tax_boxes = _extract_boxes(["cgst", "sgst", "igst"], fields)

    # 1. CGST / SGST Symmetry Check
    has_cgst = cgst_status == "resolved" and cgst is not None
    has_sgst = sgst_status == "resolved" and sgst is not None

    if has_cgst and has_sgst:
        diff = abs(cgst - sgst)  # type: ignore[operator]
        if diff <= LINE_ITEM_TOLERANCE:
            results.append(
                DetectorResult(
                    name="cgst_sgst_symmetry",
                    score=0.0,
                    confidence=0.90,
                    status="passed",
                    evidence=f"CGST ({cgst}) and SGST ({sgst}) are symmetric and equal, consistent with intra-state GST rules.",
                    boxes=tax_boxes,
                )
            )
        else:
            results.append(
                DetectorResult(
                    name="cgst_sgst_symmetry",
                    score=0.80,
                    confidence=0.85,
                    status="suspicious",
                    evidence=(
                        f"Asymmetric intra-state GST amounts: CGST ({cgst}) != SGST ({sgst}) (difference: {diff}). "
                        "Indian GST law mandates equal CGST and SGST rates and amounts for intra-state supplies."
                    ),
                    boxes=tax_boxes,
                )
            )
    elif has_cgst != has_sgst:
        present_name = "CGST" if has_cgst else "SGST"
        present_val = cgst if has_cgst else sgst
        missing_name = "SGST" if has_cgst else "CGST"
        results.append(
            DetectorResult(
                name="cgst_sgst_symmetry",
                score=0.70,
                confidence=0.80,
                status="suspicious",
                evidence=(
                    f"Unpaired intra-state tax component: {present_name} ({present_val}) is present, "
                    f"but {missing_name} is missing. Intra-state GST requires both components."
                ),
                boxes=tax_boxes,
            )
        )
    else:
        results.append(
            DetectorResult(
                name="cgst_sgst_symmetry",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence="Intra-state tax fields (CGST/SGST) are not present in extracted data.",
                boxes=[],
            )
        )

    # 2. IGST vs CGST/SGST Jurisdictional Application
    has_igst = igst_status == "resolved" and igst is not None and igst > Decimal("0.00")
    has_intra = (has_cgst and cgst > Decimal("0.00")) or (has_sgst and sgst > Decimal("0.00"))  # type: ignore[operator]

    # Check supplier state and place of supply
    supplier_state = fields.get("supplier_state") or fields.get("supplier_location")
    pos_state = fields.get("place_of_supply") or fields.get("pos")

    sup_str = str(supplier_state[0] if isinstance(supplier_state, list) and supplier_state else supplier_state).strip() if supplier_state else ""
    pos_str = str(pos_state[0] if isinstance(pos_state, list) and pos_state else pos_state).strip() if pos_state else ""

    if has_igst and has_intra:
        results.append(
            DetectorResult(
                name="gst_jurisdiction_consistency",
                score=0.75,
                confidence=0.85,
                status="suspicious",
                evidence=(
                    f"Simultaneous presence of inter-state IGST ({igst}) and intra-state CGST/SGST ({cgst}/{sgst}). "
                    "A single supply cannot be concurrently inter-state and intra-state without explicit multi-item jurisdiction."
                ),
                boxes=tax_boxes,
            )
        )
    elif sup_str and pos_str:
        # Both locations explicitly known
        is_same_state = (sup_str.lower() == pos_str.lower())
        if is_same_state and has_igst:
            results.append(
                DetectorResult(
                    name="gst_jurisdiction_consistency",
                    score=0.80,
                    confidence=0.85,
                    status="suspicious",
                    evidence=(
                        f"IGST ({igst}) levied for intra-state supply: supplier state '{sup_str}' "
                        f"matches place of supply '{pos_str}'."
                    ),
                    boxes=tax_boxes,
                )
            )
        elif not is_same_state and has_intra:
            results.append(
                DetectorResult(
                    name="gst_jurisdiction_consistency",
                    score=0.80,
                    confidence=0.85,
                    status="suspicious",
                    evidence=(
                        f"Intra-state CGST/SGST ({cgst}/{sgst}) levied for inter-state supply: "
                        f"supplier state '{sup_str}' differs from place of supply '{pos_str}'."
                    ),
                    boxes=tax_boxes,
                )
            )
        elif (is_same_state and has_intra) or (not is_same_state and has_igst):
            results.append(
                DetectorResult(
                    name="gst_jurisdiction_consistency",
                    score=0.0,
                    confidence=0.90,
                    status="passed",
                    evidence=(
                        f"Tax jurisdiction is consistent: {'intra-state' if is_same_state else 'inter-state'} "
                        f"supply from '{sup_str}' to '{pos_str}' with matching tax types."
                    ),
                    boxes=tax_boxes,
                )
            )
        else:
            results.append(
                DetectorResult(
                    name="gst_jurisdiction_consistency",
                    score=0.0,
                    confidence=0.0,
                    status="inconclusive",
                    evidence="No tax amounts applied to compare against known supplier and place of supply locations.",
                    boxes=[],
                )
            )
    else:
        # Supplier or place of supply not explicitly provided
        results.append(
            DetectorResult(
                name="gst_jurisdiction_consistency",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence=(
                    "Supplier location or place of supply is not explicitly extracted; "
                    "cannot determine inter-state vs intra-state jurisdiction (per rules, place of supply is not inferred from GSTIN alone)."
                ),
                boxes=[],
            )
        )

    # 3. Tax Amount vs Taxable Value & Rate
    raw_rate = fields.get("tax_rate") or fields.get("gst_rate")
    extracted_rate: Decimal | None = None
    if isinstance(raw_rate, list) and raw_rate:
        extracted_rate = _parse_tax_rate(raw_rate[0])
    elif raw_rate is not None and not isinstance(raw_rate, list):
        extracted_rate = _parse_tax_rate(raw_rate)

    total_tax = Decimal("0.00")
    tax_count = 0
    if has_cgst:
        total_tax += cgst  # type: ignore[operator]
        tax_count += 1
    if has_sgst:
        total_tax += sgst  # type: ignore[operator]
        tax_count += 1
    if has_igst:
        total_tax += igst  # type: ignore[operator]
        tax_count += 1

    if sub_status == "resolved" and subtotal is not None and subtotal > Decimal("0.00") and tax_count > 0:
        if extracted_rate is not None:
            expected_tax = (subtotal * extracted_rate) / Decimal("100")
            diff = abs(total_tax - expected_tax)
            if diff <= DEFAULT_ROUNDING_TOLERANCE:
                results.append(
                    DetectorResult(
                        name="tax_rate_arithmetic",
                        score=0.0,
                        confidence=0.90,
                        status="passed",
                        evidence=(
                            f"Total extracted tax ({total_tax}) matches explicitly extracted tax rate {extracted_rate}% "
                            f"on subtotal {subtotal} (expected {expected_tax}, diff {diff})."
                        ),
                        boxes=tax_boxes,
                    )
                )
            else:
                results.append(
                    DetectorResult(
                        name="tax_rate_arithmetic",
                        score=0.75,
                        confidence=0.85,
                        status="suspicious",
                        evidence=(
                            f"Tax amount discrepancy: extracted tax is {total_tax}, but {extracted_rate}% "
                            f"on subtotal {subtotal} yields expected {expected_tax} (diff: {diff}, exceeds tolerance {DEFAULT_ROUNDING_TOLERANCE})."
                        ),
                        boxes=tax_boxes,
                    )
                )
        else:
            # No explicit rate extracted. Do NOT assume 18%.
            effective_rate = (total_tax / subtotal) * Decimal("100")
            # Check if effective rate is close to any standard slab
            closest_slab = min(STANDARD_GST_SLABS, key=lambda s: abs(s - effective_rate))
            if abs(closest_slab - effective_rate) <= Decimal("0.5"):
                results.append(
                    DetectorResult(
                        name="tax_rate_arithmetic",
                        score=0.0,
                        confidence=0.75,
                        status="passed",
                        evidence=(
                            f"Effective tax rate is {effective_rate:.2f}% (consistent with standard GST slab {closest_slab}%). "
                            "No explicit tax rate extracted."
                        ),
                        boxes=tax_boxes,
                    )
                )
            else:
                results.append(
                    DetectorResult(
                        name="tax_rate_arithmetic",
                        score=0.0,
                        confidence=0.0,
                        status="inconclusive",
                        evidence=(
                            f"Effective tax rate is {effective_rate:.2f}%. No explicit tax rate extracted; "
                            "rate cannot be verified conclusively without explicit line-item or rate context."
                        ),
                        boxes=tax_boxes,
                    )
                )
    else:
        results.append(
            DetectorResult(
                name="tax_rate_arithmetic",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence="Subtotal or tax components missing; cannot verify tax rate arithmetic.",
                boxes=[],
            )
        )

    return results
