"""QR code analysis and cross-verification module.

Detects, decodes, and cross-references document QR codes against extracted fields.

Distinguishes 4 explicit levels of validation:
1. QR detected: Whether one or more QR code symbols exist on rendered pages.
2. QR decoded: Whether the barcode payload could be extracted into string/bytes.
3. Payload consistency checked: Whether parsed fields (GSTIN, Invoice #, Total, Date)
   match the document's extracted fields.
4. Cryptographic signature verified: Never claimed unless verified against trusted keys
   (standard IRP public keys).
"""

from __future__ import annotations

import base64
import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.detectors.consistency.arithmetic import (
    DEFAULT_ROUNDING_TOLERANCE,
    parse_decimal_candidate,
    resolve_candidate_field,
)
from app.schemas import BoundingBox, DetectorResult

logger = logging.getLogger(__name__)


def _decode_jwt_payload_unverified(jwt_token: str) -> dict[str, Any] | None:
    """Decodes JWT payload claims without verifying cryptographic signature."""
    parts = jwt_token.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        # Standard base64url decode with padding
        payload_b64 = parts[1]
        rem = len(payload_b64) % 4
        if rem > 0:
            payload_b64 += "=" * (4 - rem)
        raw_json = base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8")
        data = json.loads(raw_json)
        # If payload contains nested 'data' string (common in NIC/IRP e-invoices)
        if isinstance(data, dict) and "data" in data and isinstance(data["data"], str):
            try:
                data = json.loads(data["data"])
            except Exception:
                pass
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def parse_qr_payload(payload_str: str) -> dict[str, Any]:
    """Parses QR code text into structured dictionary, supporting JWT, JSON, UPI, or text."""
    clean = payload_str.strip()
    if not clean:
        return {}

    # 1. Attempt JWT decoding (IRP signed e-invoice QR code)
    if clean.count(".") == 2 and not clean.startswith("http"):
        jwt_claims = _decode_jwt_payload_unverified(clean)
        if jwt_claims:
            return {"type": "einvoice_jwt", "claims": jwt_claims, "signed": True}

    # 2. Attempt JSON format
    if clean.startswith("{") and clean.endswith("}"):
        try:
            parsed = json.loads(clean)
            if isinstance(parsed, dict):
                return {"type": "json", "data": parsed, "signed": False}
        except Exception:
            pass

    # 3. Attempt UPI format (upi://pay?pa=...&am=...&tr=...)
    if clean.startswith("upi://pay"):
        try:
            parsed_url = urlparse(clean)
            params = parse_qs(parsed_url.query)
            flattened = {k: v[0] for k, v in params.items() if v}
            return {"type": "upi", "data": flattened, "signed": False}
        except Exception:
            pass

    return {"type": "raw_text", "text": clean, "signed": False}


def _scan_page_images_for_qr(pages: list[Path]) -> list[dict[str, Any]]:
    """Attempts to scan rendered page images for QR codes using available system libraries."""
    detected: list[dict[str, Any]] = []

    # Try pyzbar if available
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode  # type: ignore[import-untyped]
        from PIL import Image  # type: ignore[import-untyped]

        for p_idx, p_path in enumerate(pages):
            if not p_path.exists():
                continue
            with Image.open(p_path) as img:
                barcodes = pyzbar_decode(img)
                for b in barcodes:
                    if b.type == "QRCODE":
                        payload = b.data.decode("utf-8", errors="ignore")
                        rect = b.rect
                        detected.append(
                            {
                                "payload": payload,
                                "page": p_idx,
                                "bbox": [rect.left, rect.top, rect.width, rect.height],
                            }
                        )
        return detected
    except ImportError:
        pass

    # Try cv2 if available
    try:
        import cv2  # type: ignore[import-untyped]

        qr_detector = cv2.QRCodeDetector()
        for p_idx, p_path in enumerate(pages):
            if not p_path.exists():
                continue
            img = cv2.imread(str(p_path))
            if img is not None:
                val, pts, _ = qr_detector.detectAndDecode(img)
                if val:
                    detected.append({"payload": val, "page": p_idx, "bbox": None})
        return detected
    except ImportError:
        pass

    return detected


def validate_qr_consistency(
    pages: list[Path], fields: dict[str, Any]
) -> list[DetectorResult]:
    """Analyzes QR codes for presence, decoding, payload matching, and signature status."""
    # 1. Collect QR candidates from fields context or page scan
    qr_candidates: list[dict[str, Any]] = []

    # Check synthetic/extracted fields
    if "_qr_payload" in fields and fields["_qr_payload"]:
        raw_p = fields["_qr_payload"]
        if isinstance(raw_p, list):
            for item in raw_p:
                qr_candidates.append({"payload": str(item), "page": 0, "bbox": None})
        else:
            qr_candidates.append({"payload": str(raw_p), "page": 0, "bbox": None})

    if "_qr_codes" in fields and isinstance(fields["_qr_codes"], list):
        for item in fields["_qr_codes"]:
            if isinstance(item, dict):
                qr_candidates.append(item)
            elif isinstance(item, str):
                qr_candidates.append({"payload": item, "page": 0, "bbox": None})

    # If none found in fields, attempt scanning rendered pages
    if not qr_candidates and pages:
        qr_candidates = _scan_page_images_for_qr(pages)

    if not qr_candidates:
        return [
            DetectorResult(
                name="qr_code_consistency",
                score=0.0,
                confidence=0.0,
                status="not_applicable" if pages else "inconclusive",
                evidence=(
                    "No QR code detected or extracted from document. "
                    "QR validation levels: detected=False, decoded=False, payload_checked=False, signature_verified=False."
                ),
                boxes=[],
            )
        ]

    # Process first QR candidate
    qr_item = qr_candidates[0]
    raw_payload = qr_item.get("payload", "")
    page_idx = qr_item.get("page", 0)
    raw_bbox = qr_item.get("bbox")

    boxes: list[BoundingBox] = []
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            x, y, w, h = int(raw_bbox[0]), int(raw_bbox[1]), int(raw_bbox[2]), int(raw_bbox[3])
            if w > 0 and h > 0:
                boxes.append(BoundingBox(page=page_idx, x=x, y=y, w=w, h=h))
        except (ValueError, TypeError):
            pass

    parsed = parse_qr_payload(raw_payload)
    qr_type = parsed.get("type", "unknown")
    is_signed = parsed.get("signed", False)

    # Cross-reference decoded payload with document fields
    doc_gstin, _, _ = resolve_candidate_field("gstin", fields)
    doc_inv, _, _ = resolve_candidate_field("invoice_number", fields)
    doc_total, _, _ = resolve_candidate_field("total", fields)

    mismatches: list[str] = []
    matched_items: list[str] = []

    claims = parsed.get("claims") or parsed.get("data") or {}

    # E-Invoice claims keys: SellerGstin, DocNo, TotInvVal, DocDt
    qr_gstin = claims.get("SellerGstin") or claims.get("seller_gstin") or claims.get("gstin")
    qr_doc_no = claims.get("DocNo") or claims.get("doc_no") or claims.get("invoice_number")
    qr_total_val = claims.get("TotInvVal") or claims.get("total") or claims.get("am")  # 'am' for UPI

    if qr_gstin:
        extracted_gstins = [str(g).strip().upper() for g in fields.get("gstin", [])]
        if extracted_gstins:
            if str(qr_gstin).strip().upper() in extracted_gstins:
                matched_items.append(f"GSTIN matches ({qr_gstin})")
            else:
                mismatches.append(f"GSTIN mismatch: QR has '{qr_gstin}', document extracted '{extracted_gstins}'")

    if qr_doc_no:
        extracted_invs = [str(i).strip().upper() for i in fields.get("invoice_number", [])]
        if extracted_invs:
            if str(qr_doc_no).strip().upper() in extracted_invs:
                matched_items.append(f"Invoice # matches ({qr_doc_no})")
            else:
                mismatches.append(f"Invoice # mismatch: QR has '{qr_doc_no}', document extracted '{extracted_invs}'")

    if qr_total_val:
        qr_tot_dec = parse_decimal_candidate(qr_total_val)
        if qr_tot_dec is not None and doc_total is not None:
            diff = abs(qr_tot_dec - doc_total)
            if diff <= DEFAULT_ROUNDING_TOLERANCE:
                matched_items.append(f"Grand total matches ({qr_tot_dec})")
            else:
                mismatches.append(f"Total mismatch: QR has '{qr_tot_dec}', document total is '{doc_total}' (diff {diff})")

    # Cryptographic signature verification status
    sig_note = (
        "Cryptographic signature: NOT verified (no trusted IRP public keys configured in verification environment)."
        if is_signed
        else "Cryptographic signature: N/A (unsigned QR payload)."
    )

    if mismatches:
        return [
            DetectorResult(
                name="qr_code_consistency",
                score=0.85,
                confidence=0.90,
                status="suspicious",
                evidence=(
                    f"QR code payload inconsistency detected ({qr_type}): "
                    + "; ".join(mismatches)
                    + f". QR detected=True, QR decoded=True, payload_checked=True. {sig_note}"
                ),
                boxes=boxes,
            )
        ]

    if matched_items:
        return [
            DetectorResult(
                name="qr_code_consistency",
                score=0.0,
                confidence=0.85,
                status="passed",
                evidence=(
                    f"QR code payload ({qr_type}) is consistent with document fields: "
                    + "; ".join(matched_items)
                    + f". QR detected=True, QR decoded=True, payload_checked=True. {sig_note}"
                ),
                boxes=boxes,
            )
        ]

    return [
        DetectorResult(
            name="qr_code_consistency",
            score=0.0,
            confidence=0.50,
            status="passed",
            evidence=(
                f"QR code detected and decoded ({qr_type}), but payload did not contain common standard fields "
                f"to cross-verify against document. QR detected=True, QR decoded=True, payload_checked=False. {sig_note}"
            ),
            boxes=boxes,
        )
    ]
