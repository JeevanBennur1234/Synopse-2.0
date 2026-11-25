"""Image metadata (EXIF / PNG text) forensic detector.

Scope note: Inspects image-container metadata only. PDF document metadata is
owned by file_forensics to avoid duplicate scoring.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

from app.schemas import DetectorResult

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}

EDITING_SOFTWARE_KEYWORDS = (
    "photoshop",
    "adobe",
    "gimp",
    "canva",
    "snapseed",
    "picsart",
    "lightroom",
    "affinity",
    "paint.net",
    "pixlr",
    "fotor",
    "inkscape",
    "coreldraw",
    "iloveimg",
    "photopea",
    "facetune",
)


def _parse_exif_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip().rstrip("\x00")
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(cleaned[:19], fmt)
        except ValueError:
            continue
    return None


def _extract_image_metadata(img_path: Path) -> dict[str, Any]:
    """Extract normalized EXIF and PNG/info metadata tags without modifying the file."""
    meta: dict[str, Any] = {}
    with Image.open(img_path) as img:
        # 1. PNG / general info dictionary (Software, Creation Time, XMP, etc.)
        for k, v in (img.info or {}).items():
            if isinstance(v, (str, bytes)):
                val_str = v.decode("utf-8", errors="ignore") if isinstance(v, bytes) else v
                if val_str.strip():
                    meta[f"info:{k}"] = val_str.strip()

        # 2. EXIF tags
        exif = img.getexif()
        if exif:
            for tag_id, value in exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    val_str = value.decode("utf-8", errors="ignore").strip("\x00 ")
                    if val_str:
                        meta[f"exif:{tag_name}"] = val_str
                else:
                    meta[f"exif:{tag_name}"] = value
    return meta


class ImageMetadataDetector:
    """Image metadata detector implementing the shared Detector protocol."""

    name = "image_metadata"

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
                    evidence="Invalid source path provided to image metadata detector.",
                    boxes=[],
                )
            ]

        ext = src.suffix.lower()
        if ext == ".pdf":
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="not_applicable",
                    evidence=(
                        "Image metadata detector is not applicable to PDF sources; "
                        "PDF metadata is handled by file_forensics to avoid duplicate scoring."
                    ),
                    boxes=[],
                )
            ]

        if ext not in IMAGE_EXTENSIONS:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="not_applicable",
                    evidence=f"Unsupported file format '{ext or 'unknown'}' for image metadata inspection.",
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
                    evidence=f"Source image file not found: {src.name}.",
                    boxes=[],
                )
            ]

        try:
            meta = _extract_image_metadata(src)
        except Exception as exc:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="error",
                    evidence=f"Failed to read image metadata: {exc}",
                    boxes=[],
                )
            ]

        # Filter out non-forensic Pillow internal keys like 'dpi' if nothing meaningful is present
        meaningful_keys = [
            k for k in meta if not k.endswith(":dpi") and not k.endswith(":jfif")
        ]
        if not meaningful_keys:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.2,
                    status="inconclusive",
                    evidence=(
                        "No EXIF or text metadata found in image. Metadata is commonly stripped by "
                        "messaging apps or scanners, so missing metadata does not imply forgery."
                    ),
                    boxes=[],
                )
            ]

        findings: list[str] = []
        risk_points = 0.0

        # Check editing software indicators across EXIF Software, ProcessingSoftware, and PNG info
        software_fields = [
            (k, str(v))
            for k, v in meta.items()
            if any(tok in k.lower() for tok in ("software", "creatortool", "xmp", "comment", "author"))
        ]
        matched_editors: list[str] = []
        for key, val in software_fields:
            low_val = val.lower()
            for kw in EDITING_SOFTWARE_KEYWORDS:
                if kw in low_val:
                    matched_editors.append(f"{key}='{val[:80]}'")
                    break

        if matched_editors:
            risk_points += 0.45
            findings.append(
                "Editing software indicator(s) detected: " + ", ".join(matched_editors) + "."
            )

        # Check EXIF timestamp consistency
        dt_modified = _parse_exif_datetime(meta.get("exif:DateTime"))
        dt_original = _parse_exif_datetime(meta.get("exif:DateTimeOriginal"))
        dt_digitized = _parse_exif_datetime(meta.get("exif:DateTimeDigitized"))

        if dt_original and dt_modified:
            if dt_modified < dt_original - timedelta(minutes=5):
                risk_points += 0.35
                findings.append(
                    f"Timestamp inconsistency: EXIF DateTime ({dt_modified.isoformat()}) is earlier "
                    f"than DateTimeOriginal ({dt_original.isoformat()})."
                )
            elif dt_modified - dt_original > timedelta(days=1):
                risk_points += 0.25
                findings.append(
                    f"Post-capture modification gap: EXIF DateTime ({dt_modified.isoformat()}) is "
                    f"more than 24h after DateTimeOriginal ({dt_original.isoformat()})."
                )

        if dt_original and dt_digitized and abs((dt_original - dt_digitized).total_seconds()) > 3600:
            risk_points += 0.20
            findings.append(
                f"Digitized timestamp ({dt_digitized.isoformat()}) differs from original ({dt_original.isoformat()})."
            )

        if findings:
            score = min(0.80, max(0.35, risk_points))
            confidence = 0.70 if len(findings) >= 2 else 0.58
            return [
                DetectorResult(
                    name=self.name,
                    score=round(score, 4),
                    confidence=round(confidence, 4),
                    status="suspicious",
                    evidence=(
                        " ".join(findings)
                        + " Note: image editing software or timestamp shifts can occur during benign cropping/resaving and do not alone prove forgery."
                    ),
                    boxes=[],
                )
            ]

        return [
            DetectorResult(
                name=self.name,
                score=0.05,
                confidence=0.65,
                status="passed",
                evidence=(
                    f"Inspected {len(meaningful_keys)} image metadata tag(s); "
                    "no editing software indicators or EXIF timestamp inconsistencies detected."
                ),
                boxes=[],
            )
        ]


def analyze(
    source: Path, pages: list[Path], fields: dict[str, Any]
) -> list[DetectorResult]:
    """Module-level entry point matching the Detector protocol."""
    return ImageMetadataDetector().analyze(source, pages, fields)
