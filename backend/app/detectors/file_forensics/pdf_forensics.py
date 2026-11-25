"""PDF file forensics and structural anomaly detector.

Scope: Inspects PDF document-container metadata, incremental saves, timestamp consistency,
and structural integrity. Image containers are inspected by image_metadata to avoid
duplicate scoring.

Key Checks:
1. PDF creation and modification timestamp consistency.
2. Producer and creator metadata inspection for known editing suites.
3. Incremental revision counting and structural integrity.
4. Trailing payload and embedded action inspection (/Launch, /JavaScript).
5. Missing or stripped metadata handling (stripping is common and benign).
6. Non-PDF files return status="not_applicable".
"""

from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from app.schemas import DetectorResult

# Known editing tools commonly associated with document alteration
PDF_EDITING_KEYWORDS = (
    "ilovepdf",
    "smallpdf",
    "pdfescape",
    "sejda",
    "pdfedit",
    "photoshop",
    "gimp",
    "canva",
    "foxit phantom",
    "nitro pro",
    "wondershare",
    "pdf24",
    "inkscape",
    "photopea",
)

# Standard PDF date format: D:YYYYMMDDHHmmSS[OHH'mm']
PDF_DATE_RE = re.compile(
    r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([+\-Z])?(\d{2})?'?(\d{2})?'?"
)


def parse_pdf_date(raw: str | None) -> datetime | None:
    """Parses a PDF date string (e.g. D:20261125140627+05'30') into an ISO datetime."""
    if not raw:
        return None
    raw_str = raw.strip().strip("()<>")
    m = PDF_DATE_RE.search(raw_str)
    if not m:
        # Fallback to standard ISO formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y%m%d%H%M%SZ"):
            try:
                return datetime.strptime(raw_str[:19], fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    groups = m.groups()
    year = int(groups[0])
    month = int(groups[1]) if groups[1] else 1
    day = int(groups[2]) if groups[2] else 1
    hour = int(groups[3]) if groups[3] else 0
    minute = int(groups[4]) if groups[4] else 0
    second = int(groups[5]) if groups[5] else 0

    tz_sign = groups[6]
    tz_hour = int(groups[7]) if groups[7] else 0
    tz_min = int(groups[8]) if groups[8] else 0

    tz: timezone = timezone.utc
    if tz_sign and tz_sign != "Z":
        offset_mins = tz_hour * 60 + tz_min
        if tz_sign == "-":
            offset_mins = -offset_mins
        tz = timezone(timedelta(minutes=offset_mins))

    try:
        return datetime(year, month, day, hour, minute, second, tzinfo=tz)
    except (ValueError, OverflowError):
        return None


def _extract_pdf_dict_entries(content: bytes) -> dict[str, str]:
    """Extracts key-value pairs from PDF /Info dictionaries and trailer /Info objects."""
    metadata: dict[str, str] = {}

    # Look for literal string values: /Key (Value) or /Key <Hex>
    entry_re = re.compile(rb"/([A-Za-z0-9_]+)\s*(?:\(([^()]*)\)|<([0-9A-Fa-f]+)>)")
    for match in entry_re.finditer(content):
        key = match.group(1).decode("ascii", errors="ignore")
        if match.group(2) is not None:
            val = match.group(2).decode("latin-1", errors="ignore")
        elif match.group(3) is not None:
            try:
                val = bytes.fromhex(match.group(3).decode("ascii")).decode("utf-8", errors="ignore")
            except Exception:
                val = match.group(3).decode("ascii", errors="ignore")
        else:
            val = ""

        if key in ("CreationDate", "ModDate", "Producer", "Creator", "Title", "Author", "Subject"):
            # If multiple exist, latest occurrence usually overrides
            metadata[key] = val

    return metadata


class PDFFileForensicsDetector:
    """Forensic analyzer for PDF documents, metadata, revision history, and structural integrity."""

    name = "file_forensics"

    def analyze(
        self, source: Path, pages: list[Path], fields: dict[str, Any]
    ) -> list[DetectorResult]:
        try:
            src = Path(source)
        except TypeError:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="error",
                    evidence="Invalid source path provided to file forensics detector.",
                    boxes=[],
                )
            ]

        ext = src.suffix.lower()
        if ext != ".pdf":
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="not_applicable",
                    evidence=(
                        f"File forensics is designed for PDF documents; '{ext or 'unknown'}' "
                        "container metadata is handled by image_metadata to avoid duplicate scoring."
                    ),
                    boxes=[],
                )
            ]

        if not src.exists() or not src.is_file():
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="error",
                    evidence=f"Source PDF file not found: {src.name}.",
                    boxes=[],
                )
            ]

        try:
            raw_bytes = src.read_bytes()
        except Exception as exc:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="error",
                    evidence=f"Failed to read source PDF file: {exc}",
                    boxes=[],
                )
            ]

        if not raw_bytes.startswith(b"%PDF-"):
            return [
                DetectorResult(
                    name="pdf_structural_integrity",
                    score=0.95,
                    confidence=0.95,
                    status="suspicious",
                    evidence=(
                        "Source file lacks valid %PDF- magic header at byte offset 0. "
                        "File format is malformed or disguised."
                    ),
                    boxes=[],
                )
            ]

        results: list[DetectorResult] = []

        # -------------------------------------------------------------
        # 1. Metadata Inspection: Timestamps and Producer/Creator
        # -------------------------------------------------------------
        meta = _extract_pdf_dict_entries(raw_bytes)
        creation_date = parse_pdf_date(meta.get("CreationDate"))
        mod_date = parse_pdf_date(meta.get("ModDate"))
        producer = meta.get("Producer", "")
        creator = meta.get("Creator", "")

        meta_findings: list[str] = []
        meta_score = 0.0

        # Check editing software keywords
        matched_editors: list[str] = []
        for field_name, field_val in (("Producer", producer), ("Creator", creator)):
            low_val = field_val.lower()
            for kw in PDF_EDITING_KEYWORDS:
                if kw in low_val:
                    matched_editors.append(f"{field_name}='{field_val[:60]}'")
                    break

        # Check timestamp consistency
        has_timestamp_inversion = False
        if creation_date and mod_date:
            if mod_date < creation_date - timedelta(minutes=2):
                has_timestamp_inversion = True
                meta_findings.append(
                    f"Timestamp anomaly: ModDate ({mod_date.isoformat()}) is earlier than CreationDate ({creation_date.isoformat()})."
                )
            elif mod_date - creation_date > timedelta(days=2):
                meta_findings.append(
                    f"Post-creation modification gap: ModDate ({mod_date.isoformat()}) is more than 48 hours after CreationDate ({creation_date.isoformat()})."
                )

        if not meta:
            results.append(
                DetectorResult(
                    name="pdf_metadata_integrity",
                    score=0.0,
                    confidence=0.25,
                    status="inconclusive",
                    evidence=(
                        "No document metadata (/Info or /CreationDate) found in PDF. Metadata is frequently "
                        "stripped by print-to-PDF drivers, scanners, or privacy tools and does not imply forgery."
                    ),
                    boxes=[],
                )
            )
        elif has_timestamp_inversion:
            results.append(
                DetectorResult(
                    name="pdf_metadata_integrity",
                    score=0.75,
                    confidence=0.85,
                    status="suspicious",
                    evidence=(
                        " ".join(meta_findings)
                        + " ModDate preceding CreationDate indicates anomalous clock skew or metadata manipulation."
                    ),
                    boxes=[],
                )
            )
        else:
            # Editing software or benign modification gap
            notes = []
            if matched_editors:
                notes.append(f"Editing software signature detected: {', '.join(matched_editors)}")
            if meta_findings:
                notes.extend(meta_findings)
            evidence_str = (
                ("; ".join(notes) + ". Note: legitimate editing software metadata and incremental revisions do not establish forgery.")
                if notes
                else (
                    f"PDF metadata is consistent. Producer: '{producer or 'N/A'}', "
                    f"CreationDate: {creation_date.isoformat() if creation_date else 'N/A'}. "
                    "No timestamp inversions detected."
                )
            )
            results.append(
                DetectorResult(
                    name="pdf_metadata_integrity",
                    score=0.0,
                    confidence=0.85,
                    status="passed",
                    evidence=evidence_str,
                    boxes=[],
                )
            )

        # -------------------------------------------------------------
        # 2. Structural Inspection: Incremental Revisions & Anomalies
        # -------------------------------------------------------------
        struct_findings: list[str] = []
        struct_score = 0.0

        # Count %%EOF markers (revision indicators, not verified history)
        eof_matches = list(re.finditer(rb"%%EOF", raw_bytes))
        eof_count = len(eof_matches)

        if eof_count == 0:
            struct_score += 0.85
            struct_findings.append("Missing %%EOF end-of-file marker; PDF stream is incomplete or truncated.")
        elif eof_count > 1:
            last_eof_end = eof_matches[-1].end()
            trailing_bytes = len(raw_bytes) - last_eof_end
            if trailing_bytes > 2048:
                struct_score += 0.50
                struct_findings.append(
                    f"Suspicious trailing data: {trailing_bytes} bytes detected after final %%EOF marker."
                )
            else:
                struct_findings.append(
                    f"Document contains {eof_count} incremental revision indicator(s) (%%EOF count). "
                    "Incremental saves occur in legitimate workflows (form filling, signatures, annotations) "
                    "and are revision indicators rather than verified revision history or proof of forgery."
                )
        else:
            # Single %%EOF
            last_eof_end = eof_matches[0].end()
            trailing_bytes = len(raw_bytes) - last_eof_end
            if trailing_bytes > 1024:
                struct_score += 0.45
                struct_findings.append(
                    f"Anomalous trailing data: {trailing_bytes} unreferenced bytes appended after %%EOF."
                )

        # Check for suspicious embedded actions
        if re.search(rb"/(?:Launch|JavaScript|JS)\b", raw_bytes):
            struct_score += 0.70
            struct_findings.append(
                "Active script/launch action detected (/JavaScript or /Launch) within PDF dictionary objects."
            )

        # Check startxref presence
        if not re.search(rb"startxref\s+\d+", raw_bytes):
            struct_score += 0.50
            struct_findings.append("Missing or unreadable 'startxref' cross-reference table pointer.")

        if struct_score > 0.0:
            results.append(
                DetectorResult(
                    name="pdf_structural_integrity",
                    score=min(0.90, max(0.40, struct_score)),
                    confidence=0.80,
                    status="suspicious",
                    evidence="; ".join(struct_findings),
                    boxes=[],
                )
            )
        else:
            evidence_msg = (
                "; ".join(struct_findings) + " Structure is well-formed without malicious stream actions."
                if struct_findings
                else (
                    f"PDF structure is well-formed with single standard revision ({eof_count} %%EOF), "
                    "valid startxref pointer, and no suspicious executable stream actions."
                )
            )
            results.append(
                DetectorResult(
                    name="pdf_structural_integrity",
                    score=0.0,
                    confidence=0.85,
                    status="passed",
                    evidence=evidence_msg,
                    boxes=[],
                )
            )

        return results


def analyze(
    source: Path, pages: list[Path], fields: dict[str, Any]
) -> list[DetectorResult]:
    """File forensics entry point adhering to shared Detector protocol."""
    return PDFFileForensicsDetector().analyze(source, pages, fields)
