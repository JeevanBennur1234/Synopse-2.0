from pathlib import Path
from shutil import copyfile

import fitz
import pytest

from app.detectors.consistency import analyze
from app.detectors.consistency.arithmetic import validate_invoice_arithmetic
from app.detectors.consistency.banking_date import validate_date_and_banking
from app.detectors.consistency.gstin import validate_gstin_candidates
from app.pipeline.orchestrator import execute
from app.preprocessing.document import process
from app.preprocessing.fields import locate
from app.preprocessing.tables import extract_tables

OOD = Path(__file__).resolve().parents[3] / "dataset" / "ood"


@pytest.mark.parametrize(
    ("filename", "gstin_status"),
    [("ood_clean_erp_invoice.pdf", "passed"), ("ood_erp_invalid_gstin.pdf", "suspicious")],
)
def test_erp_invoice(filename, gstin_status, tmp_path):
    source = tmp_path / filename
    copyfile(OOD / filename, source)
    pages, fields, _ = process(source)
    tables, _ = extract_tables(pages)
    fields.update(tables, _pages=pages, _field_locations=locate(pages, fields))
    findings, runs, _ = execute(source, pages, fields)
    assert all(run['status'] != 'error' for run in runs)
    statuses = {finding.name: finding.status for finding in findings}
    assert statuses["gstin_validation"] == gstin_status
    assert statuses["invoice_arithmetic_consistency"] == "passed"
    expected_flags = ["gstin_validation"] if gstin_status == "suspicious" else []
    assert [finding.name for finding in findings if finding.status == "suspicious"] == expected_flags


@pytest.mark.parametrize(
    "tax_lines",
    ["CGST (8%): 8\nUTGST (8%): 8\nCess: 2", "IGST (15%): 15\nCess: 3"],
)
def test_supported_tax_layouts(tax_lines, tmp_path):
    source = tmp_path / "tax_invoice.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 40), f"Tax invoice\nSubtotal: 100\n{tax_lines}\nGrand total: 118")
        pdf.save(source)
    pages, fields, _ = process(source)
    fields["_field_locations"] = locate(pages, fields)
    assert validate_invoice_arithmetic(fields)[0].status == "passed"


@pytest.mark.parametrize("key", ["subtotal", "total", "discount", "cgst", "utgst", "cess"])
def test_low_confidence_in_contributing_amount(key):
    fields = dict(subtotal=["100"], total=["135"], discount=["5"], cgst=["9"], utgst=["9"], cess=["3"])
    fields["_field_locations"] = {key: [{"value": fields[key][0], "confidence": 0.64}]}
    assert validate_invoice_arithmetic(fields)[0].status == "inconclusive"
    fields["_field_locations"][key][0]["confidence"] = None
    assert validate_invoice_arithmetic(fields)[0].status == "suspicious"


def test_conflicting_ifsc_with_low_confidence():
    fields = {
        "ifsc": ["HDFC0001234", "HDFC0001235"],
        "_field_locations": {"ifsc": [
            {"value": "HDFC0001234", "confidence": None},
            {"value": "HDFC0001235", "confidence": 0.64},
        ]},
    }
    finding = next(f for f in validate_date_and_banking(fields) if f.name == "ifsc_validation")
    assert finding.status == "inconclusive"


def test_mixed_gstin_checks_native_and_ocr():
    fields = {
        "gstin": ["04AABCN1234D1Z5", "04AABCN1234D1Z8"],
        "_pages": [
            {"page": 0, "method": "native_pdf", "text": "GSTIN: 04AABCN1234D1Z5"},
            {"page": 1, "method": "ocr", "text": "GSTIN: 04AABCN1234D1Z8"},
        ],
        "_field_locations": {"gstin": [
            {"page": 0, "value": "04AABCN1234D1Z5", "confidence": None},
            {"page": 1, "value": "04AABCN1234D1Z8", "confidence": 0.90},
        ]},
    }
    findings = [f for f in analyze(Path("mixed.pdf"), [], fields) if f.name == "gstin_validation"]
    assert [f.status for f in findings] == ["suspicious", "passed"]


def test_gstin_confidence_matches_invalid_candidate_value():
    fields = {
        "gstin": ["04AABCN1234D1Z8", "04AABCN1234D1Z5"],
        "_field_locations": {"gstin": [
            {"value": "04AABCN1234D1Z8", "confidence": 0.95},
            {"value": "04AABCN1234D1Z5", "confidence": 0.64},
        ]},
    }
    assert validate_gstin_candidates(fields)[0].status == "inconclusive"
    fields["_field_locations"]["gstin"][1]["confidence"] = None
    assert validate_gstin_candidates(fields)[0].status == "suspicious"


def test_declared_ocr_rates_cannot_override_low_confidence_subtotal():
    fields = {
        "subtotal": ["100"],
        "total": ["150"],
        "_pages": [{"page": 0, "method": "ocr", "text": "(9% CGST + 9% SGST)"}],
        "_field_locations": {
            "subtotal": [{"value": "100", "confidence": 0.64}],
            "total": [{"value": "150", "confidence": 0.95, "page": 0, "x": 10, "y": 10, "w": 10, "h": 10}],
        },
    }
    findings = [f for f in analyze(Path("scan.png"), [], fields) if f.name == "invoice_arithmetic_consistency"]
    assert [f.status for f in findings] == ["inconclusive"]
