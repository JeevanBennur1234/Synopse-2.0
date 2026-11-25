"""Invoice financial arithmetic validation detector.

Validates:
1. Subtotal and grand total arithmetic consistency.
2. Discount calculations when explicitly available.
3. Tax components (CGST, SGST, IGST) aggregation.
4. Line-item arithmetic (quantity * unit_price == amount).
5. Aggregation of line items against subtotal.
6. Explicit rounding tolerance with Decimal arithmetic.
7. Ambiguous conflicting candidate lists and missing-field handling.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas import BoundingBox, DetectorResult

# Rounding tolerance for financial currency comparisons (e.g. paisa or standard rupee rounding)
DEFAULT_ROUNDING_TOLERANCE = Decimal("1.00")
LINE_ITEM_TOLERANCE = Decimal("0.05")

CLEAN_NUMERIC_RE = re.compile(r"[^\d.-]")


def parse_decimal_candidate(raw: Any) -> Decimal | None:
    """Parses a candidate string into Decimal, safely stripping commas, currency symbols and spaces."""
    if raw is None:
        return None
    val_str = str(raw).strip()
    if not val_str:
        return None
    # Strip currency symbols and commas: "â‚¹ 1,000.50" -> "1000.50"
    cleaned = CLEAN_NUMERIC_RE.sub("", val_str)
    if not cleaned or cleaned in ("-", "."):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def resolve_candidate_field(
    field_key: str, fields: dict[str, Any]
) -> tuple[Decimal | None, list[str], str]:
    """Resolves a list of candidate strings for a financial field.

    Returns:
        (resolved_value, raw_candidates, status)
        where status is one of:
          - "resolved": candidate list unambiguously resolves to a single Decimal value
          - "missing": field is absent or contains no parseable numeric candidates
          - "conflicting": field contains multiple distinct, conflicting numeric candidates
    """
    raw_val = fields.get(field_key)
    if raw_val is None:
        return None, [], "missing"

    if isinstance(raw_val, list):
        candidates = [str(c).strip() for c in raw_val if str(c).strip()]
    else:
        candidates = [str(raw_val).strip()]

    if not candidates:
        return None, [], "missing"

    parsed_values: set[Decimal] = set()
    for c in candidates:
        dec = parse_decimal_candidate(c)
        if dec is not None:
            parsed_values.add(dec)

    if not parsed_values:
        return None, candidates, "missing"

    if len(parsed_values) > 1:
        return None, candidates, "conflicting"

    return parsed_values.pop(), candidates, "resolved"


def _extract_boxes(field_key: str, fields: dict[str, Any]) -> list[BoundingBox]:
    boxes: list[BoundingBox] = []
    locations = fields.get("_field_locations")
    if isinstance(locations, dict) and field_key in locations:
        loc_data = locations[field_key]
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


def has_low_field_confidence(fields: dict[str, Any], keys: tuple[str, ...]) -> bool:
    locations = fields.get("_field_locations") or {}
    for key in keys:
        if not fields.get(key):
            continue
        entries = locations.get(key, [])
        for entry in entries if isinstance(entries, list) else [entries]:
            confidence = entry.get("confidence") if isinstance(entry, dict) else None
            if isinstance(confidence, (int, float)) and 0 <= confidence < 0.65:
                return True
    return False


def validate_invoice_arithmetic(fields: dict[str, Any]) -> list[DetectorResult]:
    """Validates invoice financial arithmetic and line-item integrity."""
    results: list[DetectorResult] = []

    # 1. Resolve primary totals
    subtotal, sub_cands, sub_status = resolve_candidate_field("subtotal", fields)
    total, tot_cands, tot_status = resolve_candidate_field("total", fields)
    discount, disc_cands, disc_status = resolve_candidate_field("discount", fields)
    cgst, cgst_cands, cgst_status = resolve_candidate_field("cgst", fields)
    sgst, sgst_cands, sgst_status = resolve_candidate_field("sgst", fields)
    utgst, utgst_cands, utgst_status = resolve_candidate_field("utgst", fields)
    igst, igst_cands, igst_status = resolve_candidate_field("igst", fields)
    cess, cess_cands, cess_status = resolve_candidate_field("cess", fields)

    all_boxes = (
        _extract_boxes("subtotal", fields)
        + _extract_boxes("total", fields)
        + _extract_boxes("discount", fields)
        + _extract_boxes("cgst", fields)
        + _extract_boxes("sgst", fields)
        + _extract_boxes("utgst", fields)
        + _extract_boxes("igst", fields)
        + _extract_boxes("cess", fields)
    )

    # Check for ambiguous conflicting or unreadable non-empty candidates
    conflicting_fields = []
    unreadable_fields = []
    for fname, cands, fstatus in (
        ("subtotal", sub_cands, sub_status),
        ("total", tot_cands, tot_status),
        ("discount", disc_cands, disc_status),
        ("cgst", cgst_cands, cgst_status),
        ("sgst", sgst_cands, sgst_status),
        ("utgst", utgst_cands, utgst_status),
        ("igst", igst_cands, igst_status),
        ("cess", cess_cands, cess_status),
    ):
        if fstatus == "conflicting":
            conflicting_fields.append(f"{fname}={cands}")
        elif fstatus == "missing" and cands:
            unreadable_fields.append(f"{fname}={cands}")

    if conflicting_fields or unreadable_fields:
        detail_parts = []
        if conflicting_fields:
            detail_parts.append("conflicting candidates (" + ", ".join(conflicting_fields) + ")")
        if unreadable_fields:
            detail_parts.append("unreadable numeric values (" + ", ".join(unreadable_fields) + ")")
        results.append(
            DetectorResult(
                name="invoice_arithmetic_consistency",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence=(
                    "Ambiguous or unreadable financial fields ("
                    + "; ".join(detail_parts)
                    + "). "
                    + (
                        "Unresolved candidate ambiguity is treated as inconclusive."
                        if conflicting_fields and not unreadable_fields
                        else "Unresolved candidate ambiguity and unreadable values are treated as inconclusive."
                    )
                ),
                boxes=all_boxes,
            )
        )
    elif sub_status == "missing" or tot_status == "missing":
        # Missing values are NOT automatically zero
        results.append(
            DetectorResult(
                name="invoice_arithmetic_consistency",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence=(
                    f"Subtotal or grand total is missing (subtotal={sub_status}, total={tot_status}); "
                    "cannot verify invoice arithmetic."
                ),
                boxes=all_boxes,
            )
        )
    else:
        # Compute taxes (CGST, SGST, UTGST, IGST, and Cess)
        tax_sum = Decimal("0.00")
        has_taxes = False
        for tax_val, tax_status in (
            (cgst, cgst_status),
            (sgst, sgst_status),
            (utgst, utgst_status),
            (igst, igst_status),
            (cess, cess_status),
        ):
            if tax_status == "resolved" and tax_val is not None:
                tax_sum += tax_val
                has_taxes = True

        disc_val = discount if (disc_status == "resolved" and discount is not None) else Decimal("0.00")

        expected_total = subtotal - disc_val + tax_sum  # type: ignore[operator]
        discrepancy = abs(total - expected_total)  # type: ignore[operator]

        low_confidence = has_low_field_confidence(
            fields, ("subtotal", "total", "discount", "cgst", "sgst", "utgst", "igst", "cess")
        )
        if low_confidence:
            evidence = (
                f"Possible mismatch, verify manually: expected {expected_total}, read {total}. "
                if discrepancy > DEFAULT_ROUNDING_TOLERANCE else ""
            ) + "A contributing invoice amount has OCR confidence below 0.65."
            results.append(DetectorResult(
                name="invoice_arithmetic_consistency", score=0.0, confidence=0.0,
                status="inconclusive", evidence=evidence, boxes=all_boxes,
            ))
        elif discrepancy <= DEFAULT_ROUNDING_TOLERANCE:
            evidence_msg = (
                f"Invoice total arithmetic is consistent: subtotal ({subtotal})"
                + (f" - discount ({disc_val})" if disc_status == "resolved" else "")
                + (f" + taxes ({tax_sum})" if has_taxes else "")
                + f" = {expected_total}, matching grand total ({total}) within rounding tolerance {DEFAULT_ROUNDING_TOLERANCE}."
            )
            results.append(
                DetectorResult(
                    name="invoice_arithmetic_consistency",
                    score=0.0,
                    confidence=0.90,
                    status="passed",
                    evidence=evidence_msg,
                    boxes=all_boxes,
                )
            )
        else:
            # Check if omitting unextracted taxes matches exactly
            results.append(
                DetectorResult(
                    name="invoice_arithmetic_consistency",
                    score=0.80,
                    confidence=0.85,
                    status="suspicious",
                    evidence=(
                        f"Invoice grand total arithmetic discrepancy: subtotal ({subtotal})"
                        + (f" - discount ({disc_val})" if disc_status == "resolved" else "")
                        + (f" + taxes ({tax_sum})" if has_taxes else "")
                        + f" yields expected {expected_total}, but extracted grand total is {total} "
                        f"(discrepancy: {discrepancy}, exceeds tolerance {DEFAULT_ROUNDING_TOLERANCE})."
                    ),
                    boxes=all_boxes,
                )
            )

    # 2. Line items arithmetic check
    line_items = fields.get("_line_items")
    if not line_items or not isinstance(line_items, list):
        table_absent = fields.get("_line_items_present") is False
        results.append(
            DetectorResult(
                name="invoice_line_items_arithmetic",
                score=0.0,
                confidence=0.0,
                status="not_applicable" if table_absent else "inconclusive",
                evidence=("No labelled line-item table was found." if table_absent else
                          "A line-item table could not be extracted reliably."),
                boxes=[],
            )
        )
    else:
        line_boxes: list[BoundingBox] = []
        line_item_errors: list[str] = []
        computed_subtotal = Decimal("0.00")

        for idx, item in enumerate(line_items):
            if not isinstance(item, dict):
                continue
            desc = item.get("description", f"Item #{idx+1}")
            qty = parse_decimal_candidate(item.get("quantity"))
            price = parse_decimal_candidate(item.get("unit_price"))
            amount = parse_decimal_candidate(item.get("amount"))
            page_idx = item.get("page", 0)

            # Extract box if item provides bbox
            bbox = item.get("bbox") or item.get("box")
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                try:
                    bx, by, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                    if bw > 0 and bh > 0 and bx >= 0 and by >= 0 and page_idx >= 0:
                        line_boxes.append(BoundingBox(page=page_idx, x=bx, y=by, w=bw, h=bh))
                except (ValueError, TypeError):
                    pass

            has_product = "quantity" in item and "unit_price" in item
            if amount is None or (has_product and (qty is None or price is None)):
                line_item_errors.append(
                    f"'{desc}': missing or unparseable numeric fields (qty={item.get('quantity')}, price={item.get('unit_price')}, amount={item.get('amount')})"
                )
                continue

            expected_amt = qty * price if has_product else amount
            diff = abs(amount - expected_amt)
            if diff > LINE_ITEM_TOLERANCE:
                line_item_errors.append(
                    f"'{desc}': {qty} x {price} = {expected_amt}, but reported amount is {amount} (diff={diff})"
                )

            computed_subtotal += amount

        # Verify line items sum against subtotal
        if sub_status == "resolved" and subtotal is not None and not line_item_errors:
            sub_diff = abs(computed_subtotal - subtotal)
            if sub_diff > DEFAULT_ROUNDING_TOLERANCE:
                line_item_errors.append(
                    f"Sum of line items ({computed_subtotal}) does not match invoice subtotal ({subtotal}) "
                    f"(difference: {sub_diff}, tolerance: {DEFAULT_ROUNDING_TOLERANCE})"
                )

        if any(
            isinstance(item.get("confidence"), (int, float)) and 0 <= item["confidence"] < 0.65
            for item in line_items if isinstance(item, dict)
        ) or (sub_status == "resolved" and has_low_field_confidence(fields, ("subtotal",))):
            results.append(
                DetectorResult(
                    name="invoice_line_items_arithmetic",
                    score=0.0,
                    confidence=0.0,
                    status="inconclusive",
                    evidence=(
                        ("Possible mismatch, verify manually: " + "; ".join(line_item_errors) + ". ")
                        if line_item_errors else ""
                    ) + "A contributing line item or subtotal has OCR confidence below 0.65.",
                    boxes=line_boxes,
                )
            )
        elif not line_item_errors and sub_status != "resolved":
            results.append(DetectorResult(
                name="invoice_line_items_arithmetic", score=0.0, confidence=0.0,
                status="inconclusive", evidence="No reliable subtotal to compare with the line-item sum.",
                boxes=line_boxes,
            ))
        elif line_item_errors:
            results.append(
                DetectorResult(
                    name="invoice_line_items_arithmetic",
                    score=0.75,
                    confidence=0.85,
                    status="suspicious",
                    evidence="Line-item arithmetic inconsistency detected: " + "; ".join(line_item_errors),
                    boxes=line_boxes,
                )
            )
        else:
            results.append(
                DetectorResult(
                    name="invoice_line_items_arithmetic",
                    score=0.0,
                    confidence=0.90,
                    status="passed",
                    evidence=(
                        f"Validated {len(line_items)} line items: checked quantity x unit price where both are printed, "
                        + (
                            f"and total sum ({computed_subtotal}) matches subtotal ({subtotal})."
                            if (sub_status == "resolved" and subtotal is not None)
                            else f"and total sum is {computed_subtotal}."
                        )
                    ),
                    boxes=line_boxes,
                )
            )

    return results
