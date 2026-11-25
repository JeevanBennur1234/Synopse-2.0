"""End-to-end integration tests for consistency detector module."""

from pathlib import Path
import pytest
from app.detectors.consistency import ConsistencyDetector, analyze
from app.schemas import DetectorResult


def test_consistency_detector_protocol():
    det = ConsistencyDetector()
    assert hasattr(det, "analyze")
    assert hasattr(det, "name")
    assert det.name == "consistency"


def test_analyze_clean_invoice():
    fields = {
        "gstin": ["27AAPFU0939F1ZV"],
        "invoice_number": ["TEST-001"],
        "dates": ["25/11/2026"],
        "invoice_date": ["20/11/2026"],
        "due_date": ["25/11/2026"],
        "subtotal": ["1,000.00"],
        "cgst": ["90.00"],
        "sgst": ["90.00"],
        "total": ["1,180.00"],
        "discount": [],
        "ifsc": ["HDFC0001234"],
        "_line_items": [
            {
                "description": "Item 1",
                "quantity": "2",
                "unit_price": "500.00",
                "amount": "1000.00",
                "page": 0,
            }
        ],
    }

    results = analyze(Path("sample.pdf"), [], fields)
    assert isinstance(results, list)
    assert len(results) >= 8

    # All returned results must be valid DetectorResult instances
    for r in results:
        assert isinstance(r, DetectorResult)
        assert 0.0 <= r.score <= 1.0
        assert 0.0 <= r.confidence <= 1.0
        assert r.status in ("passed", "suspicious", "inconclusive", "not_applicable", "error")

    # Key modules must report passed
    gst_res = next(r for r in results if r.name == "gstin_validation")
    assert gst_res.status == "passed"
    assert gst_res.score == 0.0

    arith_res = next(r for r in results if r.name == "invoice_arithmetic_consistency")
    assert arith_res.status == "passed"

    sym_res = next(r for r in results if r.name == "cgst_sgst_symmetry")
    assert sym_res.status == "passed"

    line_res = next(r for r in results if r.name == "invoice_line_items_arithmetic")
    assert line_res.status == "passed"


def test_analyze_tampered_invoice():
    fields = {
        "gstin": ["29INVALID123"],  # Bad GSTIN
        "invoice_number": ["TEST-001"],
        "subtotal": ["1,000.00"],
        "cgst": ["90.00"],
        "sgst": ["150.00"],  # Asymmetric taxes
        "total": ["2,000.00"],  # Discrepant grand total
        "dates": ["31/04/2026"],  # Impossible date
        "invoice_date": ["25/11/2026"],
        "due_date": ["10/11/2026"],  # Chronology inversion
        "ifsc": ["INVALID_IFSC"],  # Bad IFSC
    }

    results = analyze(Path("sample.pdf"), [], fields)

    gst_res = next(r for r in results if r.name == "gstin_validation")
    assert gst_res.status == "suspicious"

    arith_res = next(r for r in results if r.name == "invoice_arithmetic_consistency")
    assert arith_res.status == "suspicious"

    sym_res = next(r for r in results if r.name == "cgst_sgst_symmetry")
    assert sym_res.status == "suspicious"

    cal_res = next(r for r in results if r.name == "calendar_date_validity")
    assert cal_res.status == "suspicious"

    chr_res = next(r for r in results if r.name == "date_chronology")
    assert chr_res.status == "suspicious"

    ifsc_res = next(r for r in results if r.name == "ifsc_validation")
    assert ifsc_res.status == "suspicious"


def test_analyze_empty_fields_returns_inconclusive_not_passed():
    fields = {}
    results = analyze(Path("sample.pdf"), [], fields)

    # Missing evidence must be inconclusive, never passed or assumed zero
    for r in results:
        assert r.status == "inconclusive"
        assert r.score == 0.0


def test_mixed_native_and_ocr_pdf_preserves_native_gstin_tampering():
    fields = {
        "gstin": ["99INVALID1234Z0"],
        "_pages": [
            {"page": 0, "method": "native_pdf", "text": "GSTIN: 99INVALID1234Z0"},
            {"page": 1, "method": "ocr", "text": "Scanned annexure"},
        ],
        "_field_locations": {
            "gstin": [
                {
                    "value": "99INVALID1234Z0",
                    "page": 0,
                    "bbox": [20, 20, 120, 18],
                    "confidence": None,
                }
            ]
        },
    }
    results = analyze(Path("mixed.pdf"), [], fields)
    gst_res = next(r for r in results if r.name == "gstin_validation")
    assert gst_res.status == "suspicious"


def test_ocr_only_gstin_still_softened_to_inconclusive():
    fields = {
        "gstin": ["29AABCU96O3R1ZM"],
        "_pages": [{"page": 0, "method": "ocr", "text": "GSTIN: 29AABCU96O3R1ZM"}],
        "_field_locations": {
            "gstin": [
                {
                    "value": "29AABCU96O3R1ZM",
                    "page": 0,
                    "bbox": [20, 20, 120, 18],
                    "confidence": 0.90,
                }
            ]
        },
    }
    results = analyze(Path("scan.png"), [], fields)
    gst_res = next(r for r in results if r.name == "gstin_validation")
    assert gst_res.status == "inconclusive"
