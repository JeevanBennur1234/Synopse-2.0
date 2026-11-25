"""Tests for PDF file forensics detector."""

from pathlib import Path
import pytest
from app.detectors.file_forensics import analyze
from app.detectors.file_forensics.pdf_forensics import (
    PDFFileForensicsDetector,
    parse_pdf_date,
)


def _create_minimal_pdf(
    tmp_path: Path,
    filename: str,
    creation_date: str = "D:20261125100000+05'30'",
    mod_date: str | None = None,
    producer: str = "ReportLab PDF Library - www.reportlab.com",
    creator: str = "Enterprise Billing System",
    incremental_revisions: int = 1,
    extra_action: str = "",
    trailing_junk: bytes = b"",
) -> Path:
    p = tmp_path / filename
    pdf_content = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n"
    )
    if extra_action:
        pdf_content += f"4 0 obj\n<< {extra_action} >>\nendobj\n".encode("ascii")

    mod_str = f" /ModDate ({mod_date})" if mod_date else ""
    info_dict = (
        f"5 0 obj\n<< /Producer ({producer}) /Creator ({creator}) /CreationDate ({creation_date}){mod_str} >>\nendobj\n"
    ).encode("ascii")

    pdf_content += info_dict
    pdf_content += (
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R /Info 5 0 R >>\n"
        b"startxref\n300\n%%EOF\n"
    )

    for i in range(1, incremental_revisions):
        pdf_content += (
            f"6 0 obj\n<< /Type /Annot /Subtype /Text >>\nendobj\n"
            f"xref\n0 1\n0000000500 00000 n \n"
            f"trailer\n<< /Size 7 /Root 1 0 R /Prev 300 >>\n"
            f"startxref\n{550 + i * 100}\n%%EOF\n"
        ).encode("ascii")

    if trailing_junk:
        pdf_content += trailing_junk

    p.write_bytes(pdf_content)
    return p


def test_parse_pdf_date():
    dt = parse_pdf_date("D:20261125140627+05'30'")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 11 and dt.day == 25
    assert dt.hour == 14 and dt.minute == 6 and dt.second == 27

    # UTC / Z
    dt_utc = parse_pdf_date("D:20260101120000Z")
    assert dt_utc is not None
    assert dt_utc.year == 2026 and dt_utc.month == 1

    assert parse_pdf_date(None) is None
    assert parse_pdf_date("invalid-date") is None


def test_file_forensics_non_pdf(tmp_path):
    img = tmp_path / "document.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    results = analyze(img, [], {})
    assert len(results) == 1
    assert results[0].status == "not_applicable"
    assert "image_metadata" in results[0].evidence


def test_file_forensics_clean_pdf(tmp_path):
    pdf = _create_minimal_pdf(tmp_path, "clean.pdf")
    results = analyze(pdf, [], {})
    assert len(results) == 2
    meta_res = next(r for r in results if r.name == "pdf_metadata_integrity")
    struct_res = next(r for r in results if r.name == "pdf_structural_integrity")

    assert meta_res.status == "passed"
    assert meta_res.score == 0.0
    assert struct_res.status == "passed"
    assert struct_res.score == 0.0


def test_file_forensics_editing_software_detected(tmp_path):
    pdf = _create_minimal_pdf(
        tmp_path, "edited.pdf", producer="iLovePDF REST API Client", creator="Canva Design"
    )
    results = analyze(pdf, [], {})
    meta_res = next(r for r in results if r.name == "pdf_metadata_integrity")
    assert meta_res.status == "suspicious"
    assert meta_res.score >= 0.45
    assert "Editing software signature detected" in meta_res.evidence


def test_file_forensics_timestamp_inversion(tmp_path):
    # ModDate is earlier than CreationDate
    pdf = _create_minimal_pdf(
        tmp_path,
        "inverted_time.pdf",
        creation_date="D:20261125140000Z",
        mod_date="D:20261125100000Z",
    )
    results = analyze(pdf, [], {})
    meta_res = next(r for r in results if r.name == "pdf_metadata_integrity")
    assert meta_res.status == "suspicious"
    assert "ModDate" in meta_res.evidence and "earlier than CreationDate" in meta_res.evidence


def test_file_forensics_suspicious_script_action(tmp_path):
    pdf = _create_minimal_pdf(
        tmp_path, "script.pdf", extra_action="/S /JavaScript /JS (app.alert(1);)"
    )
    results = analyze(pdf, [], {})
    struct_res = next(r for r in results if r.name == "pdf_structural_integrity")
    assert struct_res.status == "suspicious"
    assert "Active script/launch action detected" in struct_res.evidence


def test_file_forensics_incremental_revision_benign(tmp_path):
    pdf = _create_minimal_pdf(tmp_path, "signed.pdf", incremental_revisions=2)
    results = analyze(pdf, [], {})
    struct_res = next(r for r in results if r.name == "pdf_structural_integrity")
    # Legitimate incremental saves are not classified as forgery
    assert "incremental revision(s)" in struct_res.evidence


def test_file_forensics_missing_file():
    missing = Path("C:/nonexistent/file.pdf")
    results = analyze(missing, [], {})
    assert len(results) == 1
    assert results[0].status == "error"
