"""Consistency forensic detector package.

Integrates:
1. GSTIN structural and checksum validation.
2. Invoice financial arithmetic and line-item consistency.
3. Tax jurisdiction and rate symmetry checks.
4. Date chronology, IFSC structure and bank statement transaction checks.
5. QR code payload matching and cryptographic signature distinction.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any

from app.detectors.consistency.arithmetic import has_low_field_confidence, validate_invoice_arithmetic
from app.detectors.consistency.banking_date import validate_date_and_banking
from app.detectors.consistency.gstin import validate_gstin_candidates
from app.detectors.consistency.qr import validate_qr_consistency
from app.detectors.consistency.tax import validate_tax_consistency
from app.preprocessing.fields import extract
from app.schemas import DetectorResult


def _is_ocr_sourced(
    finding: DetectorResult,
    field_keys: tuple[str, ...],
    fields: dict[str, Any],
    ocr_pages: set[int],
    native_pages: set[int],
) -> bool:
    """Return True only when a finding originates from OCR pages rather than native PDF text."""
    if not ocr_pages:
        return False
    box_pages = {b.page for b in finding.boxes}
    if box_pages:
        if box_pages & native_pages:
            return False
        if box_pages <= ocr_pages:
            return True

    locs = fields.get("_field_locations")
    if isinstance(locs, dict):
        matched_pages: set[int] = set()
        for key in field_keys:
            for item in locs.get(key, []) if isinstance(locs.get(key), list) else []:
                if isinstance(item, dict) and "page" in item:
                    matched_pages.add(int(item["page"]))
        if matched_pages:
            if matched_pages & native_pages:
                return False
            if matched_pages <= ocr_pages:
                return True

    return not native_pages


def _unconfirmed_ocr_identifier(finding: DetectorResult) -> DetectorResult:
    return finding.model_copy(update={
        "status": "inconclusive",
        "score": 0.0,
        "confidence": 0.0,
        "evidence": "OCR-extracted identifier failed validation; verify the characters against the original image.",
    })


class ConsistencyDetector:
    """Document business rules and financial consistency detector implementing Detector protocol."""

    name = "consistency"

    def analyze(
        self, source: Path, pages: list[Path], fields: dict[str, Any]
    ) -> list[DetectorResult]:
        """Analyzes extracted fields and rendered pages for financial and structural consistency."""
        findings: list[DetectorResult] = []

        # A mixed PDF can contain independent native and OCR GSTIN candidates.
        native_gstin, ocr_gstin = set(), set()
        for page in fields.get("_pages", []):
            if page.get("method") == "native_pdf":
                native_gstin.update(extract(page.get("text", ""))["gstin"])
            elif page.get("method") == "ocr":
                ocr_gstin.update(extract(page.get("text", ""))["gstin"])
        raw_gstin = fields.get("gstin")
        if native_gstin and ocr_gstin and isinstance(raw_gstin, list):
            ocr_only = ocr_gstin - native_gstin
            for candidates, method in (
                ([value for value in raw_gstin if value not in ocr_only], "native_pdf"),
                ([value for value in raw_gstin if value in ocr_only], "ocr"),
            ):
                if not candidates:
                    continue
                page_numbers = {
                    page.get("page") for page in fields["_pages"] if page.get("method") == method
                }
                locations = fields.get("_field_locations", {})
                gstin_locations = locations.get("gstin", [])
                gstin_locations = gstin_locations if isinstance(gstin_locations, list) else [gstin_locations]
                source_fields = {
                    **fields,
                    "gstin": candidates,
                    "_field_locations": {
                        **locations,
                        "gstin": [
                            item for item in gstin_locations
                            if isinstance(item, dict) and item.get("page") in page_numbers
                        ],
                    },
                }
                for finding in validate_gstin_candidates(source_fields):
                    if method == "ocr" and finding.status == "suspicious":
                        finding = _unconfirmed_ocr_identifier(finding)
                    findings.append(finding)
        else:
            findings.extend(validate_gstin_candidates(fields))

        # 2. Invoice Financial Arithmetic & Line Items
        findings.extend(validate_invoice_arithmetic(fields))

        # 3. Tax Symmetry & Jurisdiction Consistency
        findings.extend(validate_tax_consistency(fields))

        # 4. Dates, Chronology, IFSC and Bank Statement Running Balances
        findings.extend(validate_date_and_banking(fields))

        # 5. QR Code Presence, Decoding & Field Cross-Verification
        findings.extend(validate_qr_consistency(pages, fields))

        page_list = fields.get("_pages", [])
        ocr_page_list = [p for p in page_list if p.get("method") == "ocr"]
        ocr_pages = {int(p["page"]) for p in ocr_page_list if "page" in p}
        native_pages = {int(p["page"]) for p in page_list if p.get("method") == "native_pdf" and "page" in p}

        if ocr_page_list:
            ocr_text = "\n".join(p.get("text", "") for p in ocr_page_list)
            for i, f in enumerate(findings):
                if (
                    f.status == "suspicious"
                    and f.name == "invoice_arithmetic_consistency"
                    and _is_ocr_sourced(
                        f, ("subtotal", "total", "cgst", "sgst", "utgst", "igst", "cess", "discount"), fields, ocr_pages, native_pages
                    )
                ):
                    missing_tax = any(
                        re.search(r"\b" + k + r"\b", ocr_text, re.I) and not fields.get(k.lower())
                        for k in ("CGST", "SGST", "IGST", "UTGST", "cess")
                    )
                    if missing_tax:
                        findings[i] = f.model_copy(
                            update={
                                "status": "inconclusive",
                                "score": 0.0,
                                "confidence": 0.0,
                                "evidence": "OCR did not reliably extract all declared tax components; arithmetic discrepancy requires manual verification.",
                                "boxes": [],
                            }
                        )

            # Explicit paired rates on OCR pages support an independent arithmetic check.
            rate = re.search(r"\((\d+(?:\.\d+)?)%\s*CGST\s*\+\s*(\d+(?:\.\d+)?)%\s*SGST\)", ocr_text, re.I)
            already_suspicious_arith = any(
                f.name == "invoice_arithmetic_consistency" and f.status == "suspicious" for f in findings
            )
            if (
                not already_suspicious_arith
                and rate
                and not has_low_field_confidence(
                    fields, ("subtotal", "total", "discount", "cgst", "sgst", "utgst", "igst", "cess")
                )
                and len(fields.get("subtotal", [])) == len(fields.get("total", [])) == 1
            ):
                try:
                    sub, total = (Decimal(fields[k][0].replace(",", "")) for k in ("subtotal", "total"))
                    expected = sub * (1 + (Decimal(rate[1]) + Decimal(rate[2])) / 100)
                    if total - expected > 1 and not re.search(
                        r"\b(?:cess|surcharge|freight|shipping|rounding|other charges)\b", ocr_text, re.I
                    ):
                        boxes = [
                            dict(page=x["page"], x=x["x"], y=x["y"], w=x["w"], h=x["h"])
                            for x in fields.get("_field_locations", {}).get("total", [])
                            if isinstance(x.get("confidence"), (int, float)) and x["confidence"] >= 0.65
                        ]
                        if boxes:
                            findings = [f for f in findings if f.name != "invoice_arithmetic_consistency"]
                            findings.append(
                                DetectorResult(
                                    name="invoice_arithmetic_consistency",
                                    status="suspicious",
                                    score=0.75,
                                    confidence=0.65,
                                    evidence=(
                                        f"Extracted total {total} exceeds subtotal plus explicitly declared CGST/SGST rates ({expected}); "
                                        "verify unreadable charges and original invoice."
                                    ),
                                    boxes=boxes,
                                )
                            )
                except (InvalidOperation, TypeError):
                    pass

            for i, f in enumerate(findings):
                if f.status == "suspicious" and f.name in ("gstin_validation", "ifsc_validation"):
                    key = ("gstin",) if f.name == "gstin_validation" else ("ifsc",)
                    if _is_ocr_sourced(f, key, fields, ocr_pages, native_pages):
                        findings[i] = _unconfirmed_ocr_identifier(f)
        return findings


def analyze(
    source: Path, pages: list[Path], fields: dict[str, Any]
) -> list[DetectorResult]:
    """Module-level entry point matching shared Detector protocol."""
    return ConsistencyDetector().analyze(source, pages, fields)


__all__ = [
    "ConsistencyDetector",
    "analyze",
    "validate_gstin_candidates",
    "validate_invoice_arithmetic",
    "validate_tax_consistency",
    "validate_date_and_banking",
    "validate_qr_consistency",
]
