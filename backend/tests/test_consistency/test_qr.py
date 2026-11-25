"""Tests for QR code consistency detector."""

import json
import base64
import pytest
from app.detectors.consistency.qr import (
    parse_qr_payload,
    validate_qr_consistency,
)


def _make_dummy_jwt(payload_dict: dict) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').decode("ascii").rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(payload_dict).encode("utf-8")).decode("ascii").rstrip("=")
    signature = base64.urlsafe_b64encode(b"dummy_signature_bytes").decode("ascii").rstrip("=")
    return f"{header}.{payload}.{signature}"


def test_parse_qr_payload_jwt():
    claims = {"SellerGstin": "27AAPFU0939F1ZV", "DocNo": "INV-100", "TotInvVal": "1180.00"}
    token = _make_dummy_jwt(claims)
    res = parse_qr_payload(token)
    assert res["type"] == "einvoice_jwt"
    assert res["signed"] is True
    assert res["claims"]["SellerGstin"] == "27AAPFU0939F1ZV"


def test_parse_qr_payload_upi():
    upi_str = "upi://pay?pa=merchant@upi&pn=Store&am=500.00&tr=TXN123"
    res = parse_qr_payload(upi_str)
    assert res["type"] == "upi"
    assert res["data"]["am"] == "500.00"


def test_validate_qr_consistency_clean_matching():
    claims = {"SellerGstin": "27AAPFU0939F1ZV", "DocNo": "TEST-001", "TotInvVal": "1180.00"}
    token = _make_dummy_jwt(claims)

    fields = {
        "gstin": ["27AAPFU0939F1ZV"],
        "invoice_number": ["TEST-001"],
        "total": ["1,180.00"],
        "_qr_payload": token,
    }
    results = validate_qr_consistency([], fields)
    assert len(results) == 1
    res = results[0]
    assert res.status == "passed"
    assert res.score == 0.0
    assert "QR detected=True" in res.evidence
    assert "payload_checked=True" in res.evidence
    assert "Cryptographic signature: NOT verified" in res.evidence


def test_validate_qr_consistency_mismatch_detected():
    # QR has total 50000.00, document has 1180.00
    claims = {"SellerGstin": "27AAPFU0939F1ZV", "DocNo": "TEST-001", "TotInvVal": "50000.00"}
    token = _make_dummy_jwt(claims)

    fields = {
        "gstin": ["27AAPFU0939F1ZV"],
        "invoice_number": ["TEST-001"],
        "total": ["1,180.00"],
        "_qr_payload": token,
    }
    results = validate_qr_consistency([], fields)
    assert len(results) == 1
    res = results[0]
    assert res.status == "suspicious"
    assert res.score >= 0.8
    assert "Total mismatch" in res.evidence
    assert "Cryptographic signature: NOT verified" in res.evidence


def test_validate_qr_consistency_missing():
    fields = {"gstin": ["27AAPFU0939F1ZV"]}
    results = validate_qr_consistency([], fields)
    assert len(results) == 1
    assert results[0].status == "inconclusive"
    assert "detected=False" in results[0].evidence
