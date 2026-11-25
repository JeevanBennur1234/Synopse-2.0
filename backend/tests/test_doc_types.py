"""Synthetic regression tests for document-type profiles, validators, OCR, and verdict honesty."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from app.detectors.consistency.document_types import certificate, inclusive, statement_amounts
from app.job_worker import run_pipeline
from app.preprocessing.fields import extract
from app.preprocessing.profiles import classify, coverage
from app.schemas import DetectorResult
from app.scoring.risk import evaluate


def test_classifier_and_profiles_cover_all_document_types() -> None:
    assert classify([{"text": "Government of India\nForm GST REG-06\nRegistration Certificate\nGSTIN: 09CDIPA9960L1ZZ"}], {}, {})[0] == "gst_certificate"
    assert classify([{"text": "PhonePe Transaction Statement\nNov 24, 2026 DEBIT 240"}], {}, {})[0] == "upi_statement"
    assert classify([{"text": "Account Statement\nOpening Balance 10000"}], {}, {"_bank_transactions": [{"date": "01/11/2026"}]})[0] == "bank_statement"
    assert classify([{"text": "CASH MEMO / RECEIPT\nAll Inclusive\nNet Total: 2560.00"}], {}, {})[0] == "receipt"
    assert classify([{"text": "TAX INVOICE\nInvoice No: INV-101"}], {"invoice_number": ["INV-101"]}, {})[0] == "invoice"
    assert classify([{"text": "Random unstructured memo"}], {}, {})[0] == "other"


def test_gst_certificate_validator_with_hand_checked_oracles() -> None:
    for gstin, state, pan_ok in (
        ("09CDIPA9960L1ZZ", "Uttar Pradesh", True),
        ("27CTNPK7497R1Z9", "Maharashtra", True),
    ):
        text = (
            "Form GST REG-06\n"
            f"Registration Number : {gstin}\n"
            "Legal Name : Sample Enterprise\n"
            "Constitution of Business : Proprietorship\n"
            f"Address of Principal Place of Business : Plot 12, Sector 4, {state}\n"
            "Date of Liability : 01/07/2017\n"
            "Validity From : 01/07/2017\n"
            "Date of Issue : 15/07/2017\n"
        )
        fields = extract(text)
        fields["_pages"] = [{"page": 0, "method": "native_pdf", "text": text, "words": []}]
        results = list(certificate(fields))
        by_name = {r.name: r for r in results}
        assert by_name["certificate_state"].status == "passed"
        assert by_name["certificate_pan"].status == ("passed" if pan_ok else "suspicious")
        assert by_name["certificate_dates"].status == "passed"

    # Low-confidence OCR must yield inconclusive rather than suspicious/passed
    low_fields = {
        "gstin": ["09CDIPA9960L1ZZ"],
        "_pages": [{"page": 0, "method": "ocr", "text": "Constitution of Business: Proprietorship", "words": [{"confidence": 0.35}]}],
    }
    low_res = list(certificate(low_fields))
    assert all(r.status == "inconclusive" for r in low_res)


def test_tax_inclusive_receipt_reconciliation() -> None:
    text = (
        "RECEIPT - ALL INCLUSIVE\n"
        "Taxable Amount: 2438.10\n"
        "CGST: 60.95\n"
        "SGST: 60.95\n"
        "Net Total: 2560.00\n"
    )
    fields = extract(text)
    res = inclusive(fields)
    assert res.status == "passed"
    assert "2560" in res.evidence


def test_kea_style_single_date_receipt_is_limited_checks_not_low_100(tmp_path: Path) -> None:
    """Required test: a document with one extracted date and nothing else verifiable must show Limited checks."""
    img_path = tmp_path / "kea_synthetic.png"
    img = Image.new("RGB", (900, 1200), color=(248, 248, 248))
    draw = ImageDraw.Draw(img)
    draw.text((80, 80), "KARNATAKA EXAMINATIONS AUTHORITY RECEIPT", fill=(20, 20, 20))
    draw.text((80, 160), "Transaction Date: 01-09-2025", fill=(20, 20, 20))
    draw.text((80, 240), "Application Fee Paid", fill=(20, 20, 20))
    img.save(img_path, format="PNG")

    res = run_pipeline("test_kea", img_path)
    assert res["document_type"] == "receipt"
    assert res["verdict"] == "Limited checks"
    assert res["risk_level"] == "inconclusive"
    assert res["risk_score"] is None
    assert res["limited_evidence"] is True


def test_statement_amounts_and_typography_non_escalation() -> None:
    text = "PhonePe Transaction Statement\nNov 24, 2026 Paid to Cafe DEBIT 534\n27 Oct, 2026 DEBIT 240\n"
    fields = extract(text)
    assert "Nov 24, 2026" in fields["dates"]
    assert "27 Oct, 2026" in fields["dates"]
    fields["_pages"] = [{"page": 0, "method": "ocr", "text": text, "words": []}]
    sa = statement_amounts(fields)
    assert sa.status == "passed"

    # Typography alone must never raise risk_level above low
    runs = [
        {
            "engine": "visual",
            "status": "completed",
            "findings": [
                DetectorResult(
                    name="typography",
                    score=0.78,
                    confidence=0.60,
                    status="suspicious",
                    evidence="Layout badge color diff",
                    boxes=[],
                ).model_dump()
            ],
        },
        {
            "engine": "consistency",
            "status": "completed",
            "findings": [
                DetectorResult(
                    name="calendar_date_validity",
                    score=0.0,
                    confidence=0.85,
                    status="passed",
                    evidence="Valid dates",
                    boxes=[],
                ).model_dump(),
                DetectorResult(
                    name="statement_amounts",
                    score=0.0,
                    confidence=0.85,
                    status="passed",
                    evidence="Valid amounts",
                    boxes=[],
                ).model_dump(),
            ],
        },
    ]
    risk, _ = evaluate(runs, ("calendar_date_validity", "statement_amounts"))
    assert risk["risk_level"] == "low"
