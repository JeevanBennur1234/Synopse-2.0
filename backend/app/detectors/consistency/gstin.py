"""GSTIN structural and checksum validation module.

Validates Indian Goods and Services Tax Identification Numbers (GSTIN) against:
1. 15-character alphanumeric format structure.
2. Authoritative 2-digit state and union territory codes.
3. PAN format within characters 3-12.
4. Entity code (1-9, A-Z) and standard 14th character 'Z'.
5. Luhn Mod-36 checksum character (15th digit).
6. Multi-candidate ambiguity and OCR confidence attenuation.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas import BoundingBox, DetectorResult

# Authoritative GST State / Union Territory codes
GST_STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman and Diu (former)",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "28": "Andhra Pradesh (Old)",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh (New)",
    "38": "Ladakh",
    "97": "Other Territory",
    "99": "Centre Jurisdiction",
}

CHARS_36 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_REGEX = re.compile(
    r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
)


def compute_gstin_checksum(gstin_14: str) -> str | None:
    """Computes the expected 15th character of a 14-char GSTIN prefix using Luhn mod 36."""
    if len(gstin_14) != 14:
        return None
    factor = 1
    total = 0
    for char in gstin_14.upper():
        if char not in CHARS_36:
            return None
        code = CHARS_36.index(char)
        val = code * factor
        quotient = val // 36
        remainder = val % 36
        total += quotient + remainder
        factor = 2 if factor == 1 else 1
    check_code = (36 - (total % 36)) % 36
    return CHARS_36[check_code]


def _extract_bounding_boxes(
    field_key: str, candidate_str: str, fields: dict[str, Any]
) -> list[BoundingBox]:
    """Safely extracts bounding boxes from optional _field_locations or _pages."""
    boxes: list[BoundingBox] = []
    locations = fields.get("_field_locations")
    if isinstance(locations, dict) and field_key in locations:
        loc_data = locations[field_key]
        candidates = loc_data if isinstance(loc_data, list) else [loc_data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            # Match candidate text if provided
            item_text = item.get("text", "")
            if item_text and candidate_str and item_text.strip() != candidate_str.strip():
                continue
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


def _get_ocr_confidence(field_key: str, candidate_str: str, fields: dict[str, Any]) -> float | None:
    """Extracts OCR confidence if provided in _field_locations or _pages."""
    locations = fields.get("_field_locations")
    if isinstance(locations, dict) and field_key in locations:
        loc_data = locations[field_key]
        candidates = loc_data if isinstance(loc_data, list) else [loc_data]
        for item in candidates:
            if isinstance(item, dict):
                item_text = item.get("text", "")
                if not item_text or item_text.strip() == candidate_str.strip():
                    conf = item.get("confidence")
                    if isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0:
                        return float(conf)
    return None


def validate_gstin_candidates(fields: dict[str, Any]) -> list[DetectorResult]:
    """Validates the 'gstin' candidate list extracted from the document."""
    raw_candidates = fields.get("gstin")

    if raw_candidates is None or (isinstance(raw_candidates, list) and len(raw_candidates) == 0):
        return [
            DetectorResult(
                name="gstin_validation",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence="No GSTIN field detected in extracted document data.",
                boxes=[],
            )
        ]

    if not isinstance(raw_candidates, list):
        raw_candidates = [str(raw_candidates)]

    # Clean and deduplicate candidates
    cleaned_candidates = [str(c).strip().upper() for c in raw_candidates if str(c).strip()]
    distinct_candidates = sorted(list(set(cleaned_candidates)))

    if not distinct_candidates:
        return [
            DetectorResult(
                name="gstin_validation",
                score=0.0,
                confidence=0.0,
                status="inconclusive",
                evidence="GSTIN candidate list contained only empty or blank strings.",
                boxes=[],
            )
        ]

    # Handle multiple conflicting candidates
    if len(distinct_candidates) > 1:
        # Check if all distinct candidates are valid or conflicting
        boxes: list[BoundingBox] = []
        for c in distinct_candidates:
            boxes.extend(_extract_bounding_boxes("gstin", c, fields))

        return [
            DetectorResult(
                name="gstin_validation",
                score=0.55,
                confidence=0.70,
                status="suspicious",
                evidence=(
                    f"Multiple conflicting GSTIN candidates extracted: {distinct_candidates}. "
                    "Unresolved ambiguity in GST identity across document fields."
                ),
                boxes=boxes,
            )
        ]

    candidate = distinct_candidates[0]
    boxes = _extract_bounding_boxes("gstin", candidate, fields)
    ocr_conf = _get_ocr_confidence("gstin", candidate, fields)
    has_low_ocr = ocr_conf is not None and ocr_conf < 0.65

    # Check length and character set
    if len(candidate) != 15:
        if has_low_ocr:
            return [
                DetectorResult(
                    name="gstin_validation",
                    score=0.25,
                    confidence=round(ocr_conf, 2),  # type: ignore[arg-type]
                    status="inconclusive",
                    evidence=(
                        f"Extracted GSTIN '{candidate}' has invalid length {len(candidate)} (expected 15), "
                        f"but OCR confidence is low ({ocr_conf:.2f}). Malformed identifier is likely OCR noise."
                    ),
                    boxes=boxes,
                )
            ]
        return [
            DetectorResult(
                name="gstin_validation",
                score=0.85,
                confidence=0.85,
                status="suspicious",
                evidence=(
                    f"Extracted GSTIN '{candidate}' has invalid length ({len(candidate)} characters instead of 15)."
                ),
                boxes=boxes,
            )
        ]

    # Check structural regex
    if not GSTIN_REGEX.match(candidate):
        if has_low_ocr:
            return [
                DetectorResult(
                    name="gstin_validation",
                    score=0.30,
                    confidence=round(ocr_conf, 2),  # type: ignore[arg-type]
                    status="inconclusive",
                    evidence=(
                        f"Extracted GSTIN '{candidate}' fails structural format check, "
                        f"but low OCR confidence ({ocr_conf:.2f}) suggests potential extraction degradation."
                    ),
                    boxes=boxes,
                )
            ]
        return [
            DetectorResult(
                name="gstin_validation",
                score=0.85,
                confidence=0.85,
                status="suspicious",
                evidence=f"Extracted GSTIN '{candidate}' violates standard 15-character structural pattern.",
                boxes=boxes,
            )
        ]

    # Check state code
    state_code = candidate[:2]
    if state_code not in GST_STATE_CODES:
        if has_low_ocr:
            return [
                DetectorResult(
                    name="gstin_validation",
                    score=0.35,
                    confidence=round(ocr_conf, 2),  # type: ignore[arg-type]
                    status="inconclusive",
                    evidence=(
                        f"GSTIN '{candidate}' contains unrecognized state code '{state_code}', "
                        f"under low OCR confidence ({ocr_conf:.2f})."
                    ),
                    boxes=boxes,
                )
            ]
        return [
            DetectorResult(
                name="gstin_validation",
                score=0.90,
                confidence=0.90,
                status="suspicious",
                evidence=f"GSTIN '{candidate}' has invalid state code '{state_code}' not in authoritative GST registry list.",
                boxes=boxes,
            )
        ]

    # Check checksum (Luhn mod 36)
    expected_check = compute_gstin_checksum(candidate[:14])
    actual_check = candidate[14]
    if expected_check != actual_check:
        if has_low_ocr:
            return [
                DetectorResult(
                    name="gstin_validation",
                    score=0.35,
                    confidence=round(ocr_conf, 2),  # type: ignore[arg-type]
                    status="inconclusive",
                    evidence=(
                        f"GSTIN '{candidate}' checksum mismatch (expected '{expected_check}', got '{actual_check}'), "
                        f"with low OCR confidence ({ocr_conf:.2f}) indicating likely scan artifact."
                    ),
                    boxes=boxes,
                )
            ]
        return [
            DetectorResult(
                name="gstin_validation",
                score=0.85,
                confidence=0.85,
                status="suspicious",
                evidence=(
                    f"GSTIN '{candidate}' checksum failed: expected '{expected_check}', but found '{actual_check}'."
                ),
                boxes=boxes,
            )
        ]

    state_name = GST_STATE_CODES[state_code]
    return [
        DetectorResult(
            name="gstin_validation",
            score=0.0,
            confidence=0.90 if ocr_conf is None else max(0.60, min(0.95, ocr_conf)),
            status="passed",
            evidence=(
                f"GSTIN '{candidate}' passed structure, state code ({state_code} - {state_name}) "
                f"and Luhn Mod-36 checksum validation. Note: Valid GSTIN structure does not establish "
                "actual registration or ownership."
            ),
            boxes=boxes,
        )
    ]
