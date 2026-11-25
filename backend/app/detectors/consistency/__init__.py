"""Consistency forensic detector package.

Integrates:
1. GSTIN structural and checksum validation.
2. Invoice financial arithmetic and line-item consistency.
3. Tax jurisdiction and rate symmetry checks.
4. Date chronology, IFSC structure and bank statement transaction checks.
5. QR code payload matching and cryptographic signature distinction.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.detectors.consistency.arithmetic import validate_invoice_arithmetic
from app.detectors.consistency.banking_date import validate_date_and_banking
from app.detectors.consistency.gstin import validate_gstin_candidates
from app.detectors.consistency.qr import validate_qr_consistency
from app.detectors.consistency.tax import validate_tax_consistency
from app.schemas import DetectorResult


class ConsistencyDetector:
    """Document business rules and financial consistency detector implementing Detector protocol."""

    name = "consistency"

    def analyze(
        self, source: Path, pages: list[Path], fields: dict[str, Any]
    ) -> list[DetectorResult]:
        """Analyzes extracted fields and rendered pages for financial and structural consistency."""
        findings: list[DetectorResult] = []

        # 1. GSTIN Validation
        findings.extend(validate_gstin_candidates(fields))

        # 2. Invoice Financial Arithmetic & Line Items
        findings.extend(validate_invoice_arithmetic(fields))

        # 3. Tax Symmetry & Jurisdiction Consistency
        findings.extend(validate_tax_consistency(fields))

        # 4. Dates, Chronology, IFSC and Bank Statement Running Balances
        findings.extend(validate_date_and_banking(fields))

        # 5. QR Code Presence, Decoding & Field Cross-Verification
        findings.extend(validate_qr_consistency(pages, fields))

        # OCR-only discrepancies require corroboration when components are unreadable.
        import re
        ocr_pages=[p for p in fields.get("_pages",[]) if p.get("method")=="ocr"]
        if ocr_pages:
            text="\n".join(p["text"] for p in ocr_pages)
            for i,f in enumerate(findings):
                missing_tax=any(re.search(r"\b"+k+r"\b",text,re.I) and not fields.get(k.lower()) for k in ("CGST","SGST","IGST","UTGST","cess"))
                if f.status=="suspicious" and f.name=="invoice_arithmetic_consistency" and missing_tax:
                    findings[i]=f.model_copy(update={"status":"inconclusive","score":0.0,"confidence":0.0,"evidence":"OCR did not reliably extract all declared tax components; arithmetic discrepancy requires manual verification.","boxes":[]})
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
