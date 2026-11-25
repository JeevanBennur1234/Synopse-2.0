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
        if ocr_pages:
            from decimal import Decimal, InvalidOperation
            # Explicit paired rates support an independent arithmetic check, not invented tax amounts.
            rate=re.search(r"\((\d+(?:\.\d+)?)%\s*CGST\s*\+\s*(\d+(?:\.\d+)?)%\s*SGST\)",text,re.I)
            if rate and len(fields.get("subtotal",[]))==len(fields.get("total",[]))==1:
                try:
                    sub,total=(Decimal(fields[k][0].replace(",","")) for k in ("subtotal","total"))
                    expected=sub*(1+(Decimal(rate[1])+Decimal(rate[2]))/100)
                    # Only flag totals above the declared tax-inclusive amount; discounts cannot explain excess.
                    if total-expected>1 and not re.search(r"\b(?:cess|surcharge|freight|shipping|rounding|other charges)\b",text,re.I):
                        boxes=[dict(page=x["page"],x=x["x"],y=x["y"],w=x["w"],h=x["h"]) for x in fields.get("_field_locations",{}).get("total",[]) if x.get("confidence",0)>=.65]
                        if boxes:
                            findings=[f for f in findings if f.name!="invoice_arithmetic_consistency"]
                            findings.append(DetectorResult(name="invoice_arithmetic_consistency",status="suspicious",score=.75,confidence=.65,evidence=f"Extracted total {total} exceeds subtotal plus explicitly declared CGST/SGST rates ({expected}); verify unreadable charges and original invoice.",boxes=boxes))
                except (InvalidOperation,TypeError): pass
            for i,f in enumerate(findings):
                if f.status=="suspicious" and f.name in ("gstin_validation","ifsc_validation"):
                    findings[i]=f.model_copy(update={"status":"inconclusive","score":0.0,"confidence":0.0,"evidence":"OCR-extracted identifier failed structural validation; verify characters against the original image before concluding tampering."})
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
