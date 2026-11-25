"""Error Level Analysis (ELA) detector for JPEG business documents."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.schemas import BoundingBox, DetectorResult

JPEG_EXTENSIONS = {".jpg", ".jpeg"}
DEFAULT_RECOMPRESS_QUALITY = 90
MIN_IMAGE_DIM = 64


def _clamp_box(
    x: int, y: int, w: int, h: int, page_w: int, page_h: int, page_idx: int
) -> BoundingBox | None:
    """Clamp a bounding box to page bounds and return None if degenerate."""
    x1 = max(0, min(x, page_w - 1))
    y1 = max(0, min(y, page_h - 1))
    x2 = max(x1 + 1, min(x + w, page_w))
    y2 = max(y1 + 1, min(y + h, page_h))
    cw = x2 - x1
    ch = y2 - y1
    if cw <= 0 or ch <= 0:
        return None
    return BoundingBox(page=page_idx, x=x1, y=y1, w=cw, h=ch)


def _compute_ela_map(rgb_image: np.ndarray, quality: int = DEFAULT_RECOMPRESS_QUALITY) -> np.ndarray:
    """Recompress an RGB uint8 image as JPEG in memory and return 2D float32 error map."""
    pil_img = Image.fromarray(rgb_image, mode="RGB")
    buffer = io.BytesIO()
    pil_img.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    with Image.open(buffer) as recomp_pil:
        recomp_rgb = np.asarray(recomp_pil.convert("RGB"), dtype=np.float32)

    diff = np.abs(rgb_image.astype(np.float32) - recomp_rgb)
    # Mean absolute difference across RGB channels
    return np.mean(diff, axis=2)


def _analyze_single_image(
    img_path: Path, page_idx: int, target_size: tuple[int, int] | None = None
) -> tuple[float, float, str, list[BoundingBox], str]:
    """Run ELA on one image and return (score, confidence, status, boxes, detail)."""
    with Image.open(img_path) as pil_img:
        rgb = np.asarray(pil_img.convert("RGB"), dtype=np.uint8)

    orig_h, orig_w = rgb.shape[:2]
    if orig_h < MIN_IMAGE_DIM or orig_w < MIN_IMAGE_DIM:
        return (
            0.0,
            0.1,
            "inconclusive",
            [],
            f"Page {page_idx}: image too small ({orig_w}x{orig_h}) for reliable ELA.",
        )

    # Check for blank or nearly uniform images
    if float(np.std(rgb)) < 2.0:
        return (
            0.0,
            0.1,
            "inconclusive",
            [],
            f"Page {page_idx}: image is blank or nearly uniform; ELA is inconclusive.",
        )

    ela_map = _compute_ela_map(rgb, quality=DEFAULT_RECOMPRESS_QUALITY)

    # Smooth locally to measure patch-level compression error rather than thin text strokes.
    kernel_size = max(15, (min(orig_h, orig_w) // 40) | 1)
    kernel_size = min(kernel_size, 31)
    local_ela = cv2.boxFilter(ela_map, ddepth=-1, ksize=(kernel_size, kernel_size))

    # Suppress normal high-contrast text edges by attenuating pixels with very high local edge
    # density relative to their neighborhood, while keeping genuine patch-level ELA shifts.
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = np.sqrt(grad_x * grad_x + grad_y * grad_y)
    local_grad = cv2.boxFilter(grad_mag, ddepth=-1, ksize=(kernel_size, kernel_size))

    # Compute residual ELA above what local edge density explains.
    # Fit a simple robust linear baseline on non-zero gradient regions if possible.
    flat_ela = local_ela.ravel()
    flat_grad = local_grad.ravel()
    med_ela = float(np.median(flat_ela))
    mad_ela = float(np.median(np.abs(flat_ela - med_ela)))

    # Robust ratio adjustment: high-contrast text increases both grad and ELA slightly.
    slope = float(np.median(flat_ela / (flat_grad + 10.0)))
    adjusted_ela = np.maximum(0.0, local_ela - 0.5 * slope * local_grad)

    adj_med = float(np.median(adjusted_ela))
    adj_mad = float(np.median(np.abs(adjusted_ela - adj_med)))
    scale = max(1.4826 * adj_mad, 0.35)
    z_map = (adjusted_ela - adj_med) / scale

    # Threshold for strong localized compression anomalies
    z_thresh = 4.5
    min_abs_ela = max(med_ela + 2.5, 4.0)
    anomaly_mask = ((z_map > z_thresh) & (local_ela > min_abs_ela)).astype(np.uint8)

    # Clean up tiny isolated specks
    morph_k = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    anomaly_mask = cv2.morphologyEx(anomaly_mask, cv2.MORPH_OPEN, morph_k)
    anomaly_mask = cv2.morphologyEx(anomaly_mask, cv2.MORPH_CLOSE, morph_k)

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(anomaly_mask, connectivity=8)

    min_area = max(250, int(0.0005 * orig_w * orig_h))
    max_area = int(0.45 * orig_w * orig_h)  # Avoid flagging whole-page global recompression

    page_w, page_h = target_size if target_size else (orig_w, orig_h)
    scale_x = page_w / orig_w
    scale_y = page_h / orig_h

    boxes: list[BoundingBox] = []
    peak_z = 0.0
    total_flagged_area = 0

    for label_idx in range(1, num_labels):
        bx, by, bw, bh, area = stats[label_idx]
        if area < min_area or area > max_area:
            continue
        region_z = float(np.max(z_map[by : by + bh, bx : bx + bw]))
        peak_z = max(peak_z, region_z)
        total_flagged_area += int(area)
        clamped = _clamp_box(
            int(round(bx * scale_x)),
            int(round(by * scale_y)),
            max(1, int(round(bw * scale_x))),
            max(1, int(round(bh * scale_y))),
            page_w,
            page_h,
            page_idx,
        )
        if clamped is not None:
            boxes.append(clamped)

    if boxes:
        area_ratio = total_flagged_area / float(orig_w * orig_h)
        # Bound score strictly below 0.85 since ELA alone is not proof of forgery
        raw_score = 0.42 + min(0.28, (peak_z - z_thresh) * 0.04) + min(0.15, area_ratio * 2.0)
        score = float(np.clip(raw_score, 0.35, 0.85))
        confidence = float(np.clip(0.50 + min(0.25, (peak_z - z_thresh) * 0.03), 0.50, 0.78))
        detail = (
            f"Page {page_idx}: detected {len(boxes)} localized JPEG error-level outlier(s) "
            f"(peak z={peak_z:.1f}, median ELA={med_ela:.2f}, MAD={mad_ela:.2f})."
        )
        return score, confidence, "suspicious", boxes, detail

    # No localized anomaly found
    global_p95 = float(np.percentile(flat_ela, 95))
    score = float(np.clip((global_p95 - med_ela) / 40.0, 0.0, 0.18))
    confidence = 0.65
    detail = (
        f"Page {page_idx}: error levels appear spatially consistent "
        f"(median ELA={med_ela:.2f}, p95={global_p95:.2f})."
    )
    return score, confidence, "passed", [], detail


class ELADetector:
    """Error Level Analysis detector implementing the shared Detector protocol."""

    name = "ela"

    def analyze(
        self, source: Path, pages: list[Path], fields: dict[str, Any]
    ) -> list[DetectorResult]:
        try:
            source_path = Path(source)
        except TypeError:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="error",
                    evidence="Invalid source path provided to ELA detector.",
                    boxes=[],
                )
            ]

        ext = source_path.suffix.lower()
        if ext not in JPEG_EXTENSIONS:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="not_applicable",
                    evidence=(
                        f"ELA is not applicable to '{ext or 'unknown'}' files. "
                        "Lossless formats (e.g., PNG) and PDF-rendered pages do not preserve "
                        "original JPEG quantization history."
                    ),
                    boxes=[],
                )
            ]

        if not source_path.exists() or not source_path.is_file():
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="error",
                    evidence=f"Source JPEG file not found: {source_path.name}.",
                    boxes=[],
                )
            ]

        # Determine target page dimensions from rendered pages if provided.
        target_size: tuple[int, int] | None = None
        if pages:
            try:
                with Image.open(pages[0]) as p0:
                    target_size = p0.size
            except Exception:
                target_size = None

        try:
            score, confidence, status, boxes, detail = _analyze_single_image(
                source_path, page_idx=0, target_size=target_size
            )
        except Exception as exc:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="error",
                    evidence=f"ELA failed to process JPEG image: {exc}",
                    boxes=[],
                )
            ]

        disclaimer = (
            " Note: ELA highlights compression differences and does not alone prove forgery."
        )
        return [
            DetectorResult(
                name=self.name,
                score=round(score, 4),
                confidence=round(confidence, 4),
                status=status,
                evidence=detail + disclaimer,
                boxes=boxes,
            )
        ]


def analyze(
    source: Path, pages: list[Path], fields: dict[str, Any]
) -> list[DetectorResult]:
    """Module-level entry point matching the Detector protocol."""
    return ELADetector().analyze(source, pages, fields)
