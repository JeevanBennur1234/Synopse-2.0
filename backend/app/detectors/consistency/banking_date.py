"""Date and banking consistency detector.

Validates:
1. Calendar date validity (detecting impossible dates, leap year violations, invalid days/months).
2. Temporal invoice and due-date ordering.
3. IFSC structural format (11-character Indian Financial System Code).
4. Running balance consistency across structured transaction items (_bank_transactions).
5. Opening and closing balance consistency.
6. Conservative evidence phrasing (unusual patterns alone do not prove fraud).
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.detectors.consistency.arithmetic import (
    LINE_ITEM_TOLERANCE,
    parse_decimal_candidate,
    resolve_candidate_field,
)
from app.schemas import BoundingBox, DetectorResult

# IFSC regex: 4 alphabetic characters, followed by '0', followed by 6 alphanumeric characters
IFSC_REGEX = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

# Date pattern extractors for DD/MM/YYYY, YYYY-MM-DD, etc.
DATE_DMY_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$")
DATE_YMD_RE = re.compile(r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$")


def parse_and_validate_date(raw_date_str: str) -> tuple[date | None, str | None]:
    """Parses a date string and checks whether it represents a real calendar date.

    Returns:
        (parsed_date, error_description)
    """
    clean_str = raw_date_str.strip()
    if not clean_str:
        return None, "Empty date string"

    # Try DD/MM/YYYY or DD-MM-YYYY
    m_dmy = DATE_DMY_RE.match(clean_str)
    if m_dmy:
        day, month, year = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
        if month < 1 or month > 12:
            return None, f"Invalid month {month} in date '{clean_str}'"
        max_days = calendar.monthrange(year, month)[1]
        if day < 1 or day > max_days:
            return None, f"Invalid day {day} for month {month}/{year} in date '{clean_str}'"
        try:
            return date(year, month, day), None
        except ValueError as exc:
            return None, str(exc)

    # Try YYYY-MM-DD
    m_ymd = DATE_YMD_RE.match(clean_str)
    if m_ymd:
        year, month, day = int(m_ymd.group(1)), int(m_ymd.group(2)), int(m_ymd.group(3))
        if month < 1 or month > 12:
            return None, f"Invalid month {month} in date '{clean_str}'"
        max_days = calendar.monthrange(year, month)[1]
        if day < 1 or day > max_days:
            return None, f"Invalid day {day} for month {month}/{year} in date '{clean_str}'"
        try:
            return date(year, month, day), None
        except ValueError as exc:
            return None, str(exc)

    # General fallback with standard formats
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(clean_str, fmt).date()
            return dt, None
        except ValueError:
            continue

    return None, f"Unrecognized date format '{clean_str}'"


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


def _get_ocr_conf(field_key: str, fields: dict[str, Any]) -> float | None:
    locations = fields.get("_field_locations")
    if isinstance(locations, dict) and field_key in locations:
        loc_data = locations[field_key]
        items = loc_data if isinstance(loc_data, list) else [loc_data]
        for item in items:
            if isinstance(item, dict):
                conf = item.get("confidence")
                if isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0:
                    return float(conf)
    return None


def validate_date_and_banking(fields: dict[str, Any]) -> list[DetectorResult]:
    """Validates calendar dates, chronology, IFSC structure and bank statement transactions."""
    results: list[DetectorResult] = []

    # 1. Calendar Date Validity
    extracted_dates = fields.get("dates") or []
    if not isinstance(extracted_dates, list):
        extracted_dates = [str(extracted_dates)]

    date_boxes = _extract_boxes(["dates", "invoice_date", "due_date"], fields)
    date_errors: list[str] = []
    valid_parsed_dates: list[date] = []

    for d_str in extracted_dates:
        parsed_dt, err = parse_and_validate_date(str(d_str))
        if err:
            date_errors.append(err)
        elif parsed_dt:
            valid_parsed_dates.append(parsed_dt)

    if date_errors:
        ocr_conf = _get_ocr_conf("dates", fields)
        is_low_ocr = ocr_conf is not None and ocr_conf < 0.65
        results.append(
            DetectorResult(
                name="calendar_date_validity",
                score=0.35 if is_low_ocr else 0.80,
                confidence=round(ocr_conf, 2) if is_low_ocr else 0.85,
                status="inconclusive" if is_low_ocr else "suspicious",
                evidence=(
                    "Calendar date defect detected: " + "; ".join(date_errors)
                    + (". Low OCR confidence indicates probable scan distortion." if is_low_ocr else "")
                    + " Note: unusual or malformed dates alone do not prove fraud."
                ),
                boxes=date_boxes,
            )
        )
    elif valid_parsed_dates:
        results.append(
            DetectorResult(
                name="calendar_date_validity",
                score=0.0,
                confidence=0.90,
                status="passed",
                evidence=f"Validated {len(valid_parsed_dates)} calendar date(s); all conform to valid calendar days and leap year rules.",
                boxes=date_boxes,
            )
        )
    else:
        results.append(
            DetectorResult(
                name="calendar_date_validity",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence="No date candidates found in extracted document fields.",
                boxes=[],
            )
        )

    # 2. Invoice Date vs Due Date Chronological Ordering
    raw_inv_date = fields.get("invoice_date")
    raw_due_date = fields.get("due_date")
    inv_str = raw_inv_date[0] if isinstance(raw_inv_date, list) and raw_inv_date else (str(raw_inv_date) if raw_inv_date else "")
    due_str = raw_due_date[0] if isinstance(raw_due_date, list) and raw_due_date else (str(raw_due_date) if raw_due_date else "")

    if inv_str and due_str:
        inv_dt, _ = parse_and_validate_date(inv_str)
        due_dt, _ = parse_and_validate_date(due_str)
        if inv_dt and due_dt:
            if due_dt < inv_dt:
                results.append(
                    DetectorResult(
                        name="date_chronology",
                        score=0.70,
                        confidence=0.85,
                        status="suspicious",
                        evidence=(
                            f"Chronological anomaly: due date ({due_dt.isoformat()}) precedes "
                            f"invoice date ({inv_dt.isoformat()}). Note: unusual date ordering alone does not prove fraud."
                        ),
                        boxes=date_boxes,
                    )
                )
            else:
                results.append(
                    DetectorResult(
                        name="date_chronology",
                        score=0.0,
                        confidence=0.90,
                        status="passed",
                        evidence=f"Invoice date ({inv_dt.isoformat()}) and due date ({due_dt.isoformat()}) follow chronological order.",
                        boxes=date_boxes,
                    )
                )
        else:
            results.append(
                DetectorResult(
                    name="date_chronology",
                    score=0.0,
                    confidence=0.0,
                    status="inconclusive",
                    evidence="Could not parse invoice date or due date for chronological comparison.",
                    boxes=[],
                )
            )
    else:
        results.append(
            DetectorResult(
                name="date_chronology",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence="Both invoice date and due date are required for chronology check; one or both missing.",
                boxes=[],
            )
        )

    # 3. IFSC Code Validation
    raw_ifsc = fields.get("ifsc")
    ifsc_candidates = [str(c).strip().upper() for c in (raw_ifsc if isinstance(raw_ifsc, list) else ([str(raw_ifsc)] if raw_ifsc else [])) if str(c).strip()]
    ifsc_boxes = _extract_boxes(["ifsc"], fields)

    if not ifsc_candidates:
        results.append(
            DetectorResult(
                name="ifsc_validation",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence="No IFSC code candidates extracted from document.",
                boxes=[],
            )
        )
    else:
        distinct_ifsc = sorted(list(set(ifsc_candidates)))
        if len(distinct_ifsc) > 1:
            results.append(
                DetectorResult(
                    name="ifsc_validation",
                    score=0.60,
                    confidence=0.75,
                    status="suspicious",
                    evidence=f"Multiple conflicting IFSC candidates extracted: {distinct_ifsc}.",
                    boxes=ifsc_boxes,
                )
            )
        else:
            cand_ifsc = distinct_ifsc[0]
            ocr_conf = _get_ocr_conf("ifsc", fields)
            is_low_ocr = ocr_conf is not None and ocr_conf < 0.65

            if IFSC_REGEX.match(cand_ifsc):
                results.append(
                    DetectorResult(
                        name="ifsc_validation",
                        score=0.0,
                        confidence=0.90 if not is_low_ocr else 0.70,
                        status="passed",
                        evidence=f"IFSC code '{cand_ifsc}' conforms to the 11-character RBI standard structure.",
                        boxes=ifsc_boxes,
                    )
                )
            else:
                results.append(
                    DetectorResult(
                        name="ifsc_validation",
                        score=0.35 if is_low_ocr else 0.85,
                        confidence=round(ocr_conf, 2) if is_low_ocr else 0.85,
                        status="inconclusive" if is_low_ocr else "suspicious",
                        evidence=(
                            f"IFSC candidate '{cand_ifsc}' violates 11-character structural pattern (4 letters, '0', 6 alphanumeric characters)."
                            + (" OCR confidence is low, indicating potential character misread." if is_low_ocr else "")
                        ),
                        boxes=ifsc_boxes,
                    )
                )

    # 4. Bank Statement Transactions & Running Balance
    transactions = fields.get("_bank_transactions")
    op_balance, _, op_status = resolve_candidate_field("opening_balance", fields)
    cl_balance, _, cl_status = resolve_candidate_field("closing_balance", fields)

    if not transactions or not isinstance(transactions, list):
        results.append(
            DetectorResult(
                name="bank_statement_balance_consistency",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence="No structured bank transactions (_bank_transactions) found in extracted fields.",
                boxes=[],
            )
        )
    else:
        txn_boxes: list[BoundingBox] = []
        txn_errors: list[str] = []
        total_debits = Decimal("0.00")
        total_credits = Decimal("0.00")
        prev_balance: Decimal | None = op_balance if op_status == "resolved" else None

        for idx, txn in enumerate(transactions):
            if not isinstance(txn, dict):
                continue
            debit = parse_decimal_candidate(txn.get("debit")) or Decimal("0.00")
            credit = parse_decimal_candidate(txn.get("credit")) or Decimal("0.00")
            balance = parse_decimal_candidate(txn.get("balance"))
            page_idx = txn.get("page", 0)

            bbox = txn.get("bbox") or txn.get("box")
            if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                try:
                    bx, by, bw, bh = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
                    if bw > 0 and bh > 0 and bx >= 0 and by >= 0 and page_idx >= 0:
                        txn_boxes.append(BoundingBox(page=page_idx, x=bx, y=by, w=bw, h=bh))
                except (ValueError, TypeError):
                    pass

            total_debits += debit
            total_credits += credit

            if prev_balance is not None and balance is not None:
                expected_balance = prev_balance + credit - debit
                diff = abs(balance - expected_balance)
                if diff > LINE_ITEM_TOLERANCE:
                    desc = txn.get("description", f"Txn #{idx+1}")
                    txn_errors.append(
                        f"'{desc}' (row {idx+1}): previous balance {prev_balance} + credit {credit} - debit {debit} = {expected_balance}, but statement reported balance {balance} (diff: {diff})"
                    )

            if balance is not None:
                prev_balance = balance

        # Opening and closing balance check
        if op_status == "resolved" and cl_status == "resolved" and op_balance is not None and cl_balance is not None:
            expected_cl = op_balance + total_credits - total_debits
            diff_cl = abs(cl_balance - expected_cl)
            if diff_cl > LINE_ITEM_TOLERANCE:
                txn_errors.append(
                    f"Opening/closing balance mismatch: opening balance {op_balance} + credits {total_credits} - debits {total_debits} = {expected_cl}, but closing balance is {cl_balance} (diff: {diff_cl})"
                )

        if txn_errors:
            results.append(
                DetectorResult(
                    name="bank_statement_balance_consistency",
                    score=0.80,
                    confidence=0.85,
                    status="suspicious",
                    evidence=(
                        "Bank transaction balance discrepancies detected: " + "; ".join(txn_errors)
                        + ". Note: unusual transaction sequences alone do not prove fraud."
                    ),
                    boxes=txn_boxes,
                )
            )
        else:
            results.append(
                DetectorResult(
                    name="bank_statement_balance_consistency",
                    score=0.0,
                    confidence=0.90,
                    status="passed",
                    evidence=(
                        f"Validated {len(transactions)} bank transaction(s); running balances and net debits/credits "
                        "are strictly consistent with reported balances."
                    ),
                    boxes=txn_boxes,
                )
            )

    return results
