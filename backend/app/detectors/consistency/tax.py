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
    has_low_field_confidence,
    LINE_ITEM_TOLERANCE,
    parse_decimal_candidate,
    resolve_candidate_field,
)
from app.detectors.consistency.gstin import GST_STATE_CODES
from app.schemas import BoundingBox, DetectorResult


def _normalize_state_key(raw: str) -> str:
    """Normalize explicit state names or 2-digit GST state codes (e.g., '29 - Karnataka' -> '29')."""
    text = raw.strip().lower()
    if not text:
        return ""
    m_code = re.match(r"^(\d{2})\b", text)
    if m_code and m_code.group(1) in GST_STATE_CODES:
        return m_code.group(1)
    m_paren = re.search(r"\((\d{2})\)", text)
    if m_paren and m_paren.group(1) in GST_STATE_CODES:
        return m_paren.group(1)
    for code, name in GST_STATE_CODES.items():
        if name.lower() == text or name.lower() in text:
            return code
    return text

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
    utgst, utgst_cands, utgst_status = resolve_candidate_field("utgst", fields)
    igst, igst_cands, igst_status = resolve_candidate_field("igst", fields)
    cess, cess_cands, cess_status = resolve_candidate_field("cess", fields)
    subtotal, _, sub_status = resolve_candidate_field("subtotal", fields)

    tax_boxes = _extract_boxes(["cgst", "sgst", "utgst", "igst", "cess"], fields)

    # 1. CGST / (SGST or UTGST) Symmetry Check
    # In Union Territories without legislatures, UTGST replaces SGST.
    has_cgst = cgst_status == "resolved" and cgst is not None
    has_sgst = sgst_status == "resolved" and sgst is not None
    has_utgst = utgst_status == "resolved" and utgst is not None
    has_state_tax = has_sgst or has_utgst
    state_tax_val = sgst if has_sgst else (utgst if has_utgst else None)
    state_tax_name = "SGST" if has_sgst else ("UTGST" if has_utgst else "SGST/UTGST")

    if has_cgst and has_state_tax and state_tax_val is not None:
        diff = abs(cgst - state_tax_val)  # type: ignore[operator]
        if diff <= LINE_ITEM_TOLERANCE:
            results.append(
                DetectorResult(
                    name="cgst_sgst_symmetry",
                    score=0.0,
                    confidence=0.90,
                    status="passed",
                    evidence=(
                        f"CGST ({cgst}) and {state_tax_name} ({state_tax_val}) are symmetric and equal, "
                        "consistent with intra-state / union territory GST rules."
                    ),
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
                        f"Asymmetric intra-state GST amounts: CGST ({cgst}) != {state_tax_name} ({state_tax_val}) (diff: {diff}). "
                        "Equal CGST and state/UT rates and amounts are required for standard intra-state supplies."
                    ),
                    boxes=tax_boxes,
                )
            )
    elif has_cgst != has_state_tax:
        # Unpaired tax component: treat as inconclusive when OCR extraction may be incomplete
        present_name = "CGST" if has_cgst else state_tax_name
        present_val = cgst if has_cgst else state_tax_val
        missing_name = state_tax_name if has_cgst else "CGST"
        results.append(
            DetectorResult(
                name="cgst_sgst_symmetry",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence=(
                    f"Unpaired tax component: {present_name} ({present_val}) detected while {missing_name} was not extracted. "
                    "Incomplete OCR field extraction or single-ledger accounting cannot be ruled out; treated as inconclusive."
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
                evidence="Intra-state tax fields (CGST/SGST/UTGST) are not present in extracted data.",
                boxes=[],
            )
        )

    # 2. IGST vs CGST/SGST/UTGST Jurisdictional Application
    has_igst = igst_status == "resolved" and igst is not None and igst > Decimal("0.00")
    has_intra = (
        (has_cgst and cgst > Decimal("0.00"))
        or (has_sgst and sgst > Decimal("0.00"))
        or (has_utgst and utgst > Decimal("0.00"))
    )  # type: ignore[operator]

    # Check supplier state and place of supply
    supplier_state = fields.get("supplier_state") or fields.get("supplier_location")
    pos_state = fields.get("place_of_supply") or fields.get("pos")

    sup_str = str(supplier_state[0] if isinstance(supplier_state, list) and supplier_state else supplier_state).strip() if supplier_state else ""
    pos_str = str(pos_state[0] if isinstance(pos_state, list) and pos_state else pos_state).strip() if pos_state else ""

    gstins = fields.get("gstin") or []
    gstins = [gstins] if isinstance(gstins, str) else gstins
    state_codes = {value[:2] for value in gstins if isinstance(value, str)
                   and len(value) == 15 and value[:2] in GST_STATE_CODES}
    pos_values = [pos_state] if isinstance(pos_state, str) else (pos_state or [])
    pos_codes = {_normalize_state_key(str(value)) for value in pos_values}
    pos_code = next(iter(pos_codes)) if len(pos_codes) == 1 else ""
    gst_state_mismatch = (
        has_cgst and has_sgst and cgst > 0 and sgst > 0
        and pos_code in GST_STATE_CODES and len(state_codes) == 1 and pos_code not in state_codes
    )

    if has_igst and has_intra:
        results.append(
            DetectorResult(
                name="gst_jurisdiction_consistency",
                score=0.75,
                confidence=0.85,
                status="suspicious",
                evidence=(
                    f"Simultaneous presence of inter-state IGST ({igst}) and intra-state CGST/SGST/UTGST ({cgst}/{state_tax_val}). "
                    "A single supply cannot be concurrently inter-state and intra-state without explicit multi-item jurisdiction."
                ),
                boxes=tax_boxes,
            )
        )
    elif gst_state_mismatch:
        gst_state = GST_STATE_CODES[next(iter(state_codes))]
        results.append(DetectorResult(
            name="gst_jurisdiction_consistency", score=0.55, confidence=0.65,
            status="suspicious",
            evidence=(f"CGST and SGST are charged, but GSTIN state '{gst_state}' differs from "
                      f"explicit place of supply '{pos_str}'. This may be legitimate for special cases; "
                      "verify manually."),
            boxes=tax_boxes,
        ))
    elif sup_str and pos_str:
        # Both locations explicitly known (normalize state codes and names)
        sup_norm = _normalize_state_key(sup_str)
        pos_norm = _normalize_state_key(pos_str)
        is_same_state = (sup_norm == pos_norm)
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
                        f"Intra-state CGST/{state_tax_name} ({cgst}/{state_tax_val}) levied for inter-state supply: "
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
    has_mixed_rates = False
    if isinstance(raw_rate, list) and raw_rate:
        parsed_rates = [r for r in (_parse_tax_rate(item) for item in raw_rate) if r is not None]
        distinct_rates = set(parsed_rates)
        if len(distinct_rates) > 1:
            has_mixed_rates = True
        elif len(distinct_rates) == 1:
            extracted_rate = parsed_rates[0]
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
    if has_utgst:
        total_tax += utgst  # type: ignore[operator]
        tax_count += 1
    if has_igst:
        total_tax += igst  # type: ignore[operator]
        tax_count += 1
    if cess_status == "resolved" and cess is not None:
        total_tax += cess

    pages = fields.get("_pages")
    text = "\n".join(page.get("text", "") for page in pages or ())
    rate_present = bool(raw_rate or re.search(
        r"\b(?:gst|tax)\s+rate\b|\b(?:cgst|sgst|igst|utgst|cess)\b[ \t(]*\d+(?:\.\d+)?\s*%",
        text, re.I,
    ))
    breakdown_present = bool(tax_count or cess_status != "missing" or rate_present or re.search(
        r"\b(?:cgst|sgst|igst|utgst|cess|(?:gst|tax)\s+(?:breakdown|amount))\b",
        text, re.I,
    ))
    amount_keys = ("subtotal", "cgst", "sgst", "igst", "utgst", "cess")
    if pages and not breakdown_present and text.strip():
        results.append(DetectorResult(
            name="tax_rate_arithmetic", score=0.0, confidence=0.0,
            status="not_applicable", evidence="No tax breakdown or rate is printed.", boxes=[],
        ))
    elif has_low_field_confidence(fields, amount_keys):
        results.append(DetectorResult(
            name="tax_rate_arithmetic", score=0.0, confidence=0.0,
            status="inconclusive", evidence="A contributing tax amount or subtotal has low OCR confidence.",
            boxes=tax_boxes,
        ))
    elif sub_status == "resolved" and subtotal is not None and subtotal > Decimal("0.00") and (tax_count or cess_status == "resolved"):
        if has_mixed_rates:
            results.append(
                DetectorResult(
                    name="tax_rate_arithmetic",
                    score=0.0,
                    confidence=0.0,
                    status="inconclusive",
                    evidence="Multiple distinct tax rates extracted; mixed-rate line items require per-line tax verification and are treated as inconclusive.",
                    boxes=tax_boxes,
                )
            )
        elif extracted_rate is not None:
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
                            f"Tax amount discrepancy: extracted tax is {total_tax}, but explicitly declared rate {extracted_rate}% "
                            f"on subtotal {subtotal} yields expected {expected_tax} (diff: {diff}, exceeds tolerance {DEFAULT_ROUNDING_TOLERANCE})."
                        ),
                        boxes=tax_boxes,
                    )
                )
        else:
            # No explicit rate extracted. Do NOT assume 18% or classify unknown rates as suspicious.
            effective_rate = (total_tax / subtotal) * Decimal("100")
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
            elif pages and not rate_present:
                results.append(DetectorResult(
                    name="tax_rate_arithmetic", score=0.0, confidence=0.0,
                    status="not_applicable",
                    evidence=(f"No rate is printed to verify against the effective rate of "
                              f"{effective_rate:.2f}%. Extracted tax amounts remain part of the invoice total check."),
                    boxes=tax_boxes,
                ))
            else:
                results.append(
                    DetectorResult(
                        name="tax_rate_arithmetic",
                        score=0.0,
                        confidence=0.0,
                        status="inconclusive",
                        evidence=(
                            f"Effective tax rate is {effective_rate:.2f}%. Mixed-rate line items, cess, or special tax slabs "
                            "frequently yield non-uniform composite tax rates; treated as inconclusive."
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
