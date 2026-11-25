"""Tests for GSTIN validation detector."""

import pytest
from app.detectors.consistency.gstin import (
    GST_STATE_CODES,
    compute_gstin_checksum,
    validate_gstin_candidates,
)
from app.schemas import BoundingBox, DetectorResult


def test_gst_state_codes_contains_authoritative_entries():
    assert "01" in GST_STATE_CODES
    assert "29" in GST_STATE_CODES  # Karnataka
    assert "27" in GST_STATE_CODES  # Maharashtra
    assert "38" in GST_STATE_CODES  # Ladakh
    assert "97" in GST_STATE_CODES  # Other Territory
    assert "99" in GST_STATE_CODES  # Centre Jurisdiction
    assert "00" not in GST_STATE_CODES
    assert "98" not in GST_STATE_CODES


def test_gstin_checksum_known_vectors():
    # 27AAPFU0939F1ZV
    assert compute_gstin_checksum("27AAPFU0939F1Z") == "V"
    # 06AAACG9522H1ZP
    assert compute_gstin_checksum("06AAACG9522H1Z") == "P"
    # 29AAAAA0000A1ZY
    assert compute_gstin_checksum("29AAAAA0000A1Z") == "Y"


def test_validate_gstin_valid_candidate():
    fields = {"gstin": ["27AAPFU0939F1ZV"]}
    results = validate_gstin_candidates(fields)
    assert len(results) == 1
    res = results[0]
    assert res.name == "gstin_validation"
    assert res.status == "passed"
    assert res.score == 0.0
    assert "Valid GSTIN structure does not establish actual registration or ownership" in res.evidence
    assert res.boxes == []


def test_validate_gstin_invalid_checksum():
    # Last char changed to X instead of V
    fields = {"gstin": ["27AAPFU0939F1ZX"]}
    results = validate_gstin_candidates(fields)
    assert len(results) == 1
    res = results[0]
    assert res.status == "suspicious"
    assert res.score >= 0.8
    assert "checksum failed" in res.evidence


def test_validate_gstin_invalid_state_code():
    # 00 is not a valid state code
    fields = {"gstin": ["00AAPFU0939F1ZV"]}
    results = validate_gstin_candidates(fields)
    assert len(results) == 1
    res = results[0]
    assert res.status == "suspicious"
    assert "invalid state code" in res.evidence


def test_validate_gstin_malformed_length():
    fields = {"gstin": ["29INVALID123"]}
    results = validate_gstin_candidates(fields)
    assert len(results) == 1
    res = results[0]
    assert res.status == "suspicious"
    assert "invalid length" in res.evidence


def test_validate_gstin_missing():
    fields = {"gstin": []}
    results = validate_gstin_candidates(fields)
    assert len(results) == 1
    assert results[0].status == "inconclusive"


def test_validate_gstin_conflicting_candidates():
    fields = {"gstin": ["27AAPFU0939F1ZV", "29AAAAA0000A1ZY"]}
    results = validate_gstin_candidates(fields)
    assert len(results) == 1
    assert results[0].status == "suspicious"
    assert "Multiple conflicting GSTIN candidates" in results[0].evidence


def test_validate_gstin_identical_candidates_deduped():
    fields = {"gstin": ["27AAPFU0939F1ZV", "27AAPFU0939F1ZV"]}
    results = validate_gstin_candidates(fields)
    assert len(results) == 1
    assert results[0].status == "passed"


def test_validate_gstin_low_ocr_confidence_softens_evidence():
    fields = {
        "gstin": ["29INVALID123"],
        "_field_locations": {
            "gstin": {
                "text": "29INVALID123",
                "confidence": 0.45,
                "bbox": [100, 200, 150, 30],
                "page": 0,
            }
        },
    }
    results = validate_gstin_candidates(fields)
    assert len(results) == 1
    res = results[0]
    assert res.status == "inconclusive"
    assert "OCR confidence is low" in res.evidence
    assert len(res.boxes) == 1
    assert res.boxes[0].page == 0
    assert res.boxes[0].x == 100
