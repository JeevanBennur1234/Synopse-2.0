"""Error Level Analysis (ELA) detector for JPEG business documents."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import cv2
from PIL import Image

from app.schemas import BoundingBox, DetectorResult

JPEG_EXTENSIONS = {".jpg", ".jpeg"}
DEFAULT_RECOMPRESS_QUALITY = 90
MIN_IMAGE_DIM = 64
BLOCK_SIZE = 8


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
    """Recompress an RGB uint8 image as JPEG in memory and return 2D luminance (Y) error map.

    Using luminance (Y) avoids false positives from 4:2:0 chroma subsampling on
    colored stamps/logos while preserving 8x8 DCT quantization ringing on spliced text.
    """
    pil_img = Image.fromarray(rgb_image, mode="RGB")
    buffer = io.BytesIO()
    pil_img.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    with Image.open(buffer) as recomp_pil:
        recomp_rgb = np.asarray(recomp_pil.convert("RGB"), dtype=np.uint8)

    y_orig = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2YCrCb)[:, :, 0].astype(np.float32)
    y_recomp = cv2.cvtColor(recomp_rgb, cv2.COLOR_RGB2YCrCb)[:, :, 0].astype(np.float32)
    return np.abs(y_orig - y_recomp)


def _analyze_single_image(
    img_path: Path, page_idx: int, target_size: tuple[int, int] | None = None
) -> tuple[float, float, str, list[BoundingBox], str]:
    """Run 8x8-block edge-normalized ELA on one image."""
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

    if float(np.std(rgb)) < 2.0:
        return (
            0.0,
            0.1,
            "inconclusive",
            [],
            f"Page {page_idx}: image is blank or nearly uniform; ELA is inconclusive.",
        )

    ela_map = _compute_ela_map(rgb, quality=DEFAULT_RECOMPRESS_QUALITY)

    # Measure local edge density so normal crisp text & graphic stamps are not flagged
    # solely for having high contrast.
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = np.sqrt(grad_x * grad_x + grad_y * grad_y)

    # Aggregate on JPEG's native 8x8 DCT block grid to preserve 8x8 blockiness / ringing
    # around spliced text without diluting it over large white-paper windows.
    bh = orig_h // BLOCK_SIZE
    bw = orig_w // BLOCK_SIZE
    if bh < 4 or bw < 4:
        return (
            0.0,
            0.1,
            "inconclusive",
            [],
            f"Page {page_idx}: too few 8x8 blocks ({bw}x{bh}) for ELA.",
        )

    blk_ela = ela_map[: bh * BLOCK_SIZE, : bw * BLOCK_SIZE].reshape(
        bh, BLOCK_SIZE, bw, BLOCK_SIZE
    ).mean(axis=(1, 3))
    blk_grad = grad_mag[: bh * BLOCK_SIZE, : bw * BLOCK_SIZE].reshape(
        bh, BLOCK_SIZE, bw, BLOCK_SIZE
    ).mean(axis=(1, 3))

    # Smooth slightly in block space (3x3 = 24x24 px) to capture contiguous region elevation
    local_blk_ela = cv2.boxFilter(blk_ela, ddepth=-1, ksize=(3, 3))
    local_blk_grad = cv2.boxFilter(blk_grad, ddepth=-1, ksize=(3, 3))

    med_ela = float(np.median(local_blk_ela))
    mad_ela = float(np.median(np.abs(local_blk_ela - med_ela)))

    # Fit ELA-per-edge-unit ONLY on active blocks (where text/graphics exist)
    active_mask = local_blk_grad > 4.0
    if int(np.sum(active_mask)) >= 20:
        active_ratios = local_blk_ela[active_mask] / (local_blk_grad[active_mask] + 15.0)
        med_ratio = float(np.median(active_ratios))
        slope = 1.35 * med_ratio
        expected_ela = slope * (local_blk_grad + 15.0)
    else:
        expected_ela = np.full_like(local_blk_ela, med_ela)

    excess_ela = np.maximum(0.0, local_blk_ela - expected_ela)

    # Compute robust z-score on active blocks so 90% blank white paper doesn't collapse MAD to 0
    if int(np.sum(active_mask)) >= 20:
        act_excess = excess_ela[active_mask]
        exc_med = float(np.median(act_excess))
        exc_mad = float(np.median(np.abs(act_excess - exc_med)))
        scale = max(1.4826 * exc_mad, 0.22)
    else:
        exc_med = float(np.median(excess_ela))
        exc_mad = float(np.median(np.abs(excess_ela - exc_med)))
        scale = max(1.4826 * exc_mad, 0.22)

    z_map = (excess_ela - exc_med) / scale

    z_thresh = 3.8
    min_abs_excess = 0.75
    min_abs_blk_ela = max(med_ela + 1.8, 2.35)
    anomaly_blk = (
        (z_map > z_thresh)
        & (excess_ela > min_abs_excess)
        & (local_blk_ela > min_abs_blk_ela)
    ).astype(np.uint8)

    # Bridge 1-block gaps between words on the same spliced line
    close_k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 2))
    anomaly_blk = cv2.morphologyEx(anomaly_blk, cv2.MORPH_CLOSE, close_k)

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(anomaly_blk, connectivity=8)

    min_blk_area = 4
    max_blk_area = int(0.45 * bw * bh)

    page_w, page_h = target_size if target_size else (orig_w, orig_h)
    scale_x = page_w / float(orig_w)
    scale_y = page_h / float(orig_h)

    boxes: list[BoundingBox] = []
    peak_z = 0.0
    total_flagged_blocks = 0

    for label_idx in range(1, num_labels):
        bx, by, b_w, b_h, area = stats[label_idx]
        # Reject 1-block-thin horizontal/vertical rule lines
        if b_w < 2 or b_h < 2:
            continue
        if area < min_blk_area or area > max_blk_area:
            continue
        region_z = float(np.max(z_map[by : by + b_h, bx : bx + b_w]))
        peak_z = max(peak_z, region_z)
        total_flagged_blocks += int(area)
        px = bx * BLOCK_SIZE
        py = by * BLOCK_SIZE
        pw = b_w * BLOCK_SIZE
        ph = b_h * BLOCK_SIZE
        clamped = _clamp_box(
            int(round(px * scale_x)),
            int(round(py * scale_y)),
            max(1, int(round(pw * scale_x))),
            max(1, int(round(ph * scale_y))),
            page_w,
            page_h,
            page_idx,
        )
        if clamped is not None:
            boxes.append(clamped)

    if boxes:
        area_ratio = total_flagged_blocks / float(bw * bh)
        raw_score = 0.42 + min(0.28, (peak_z - z_thresh) * 0.03) + min(0.15, area_ratio * 2.0)
        score = float(np.clip(raw_score, 0.35, 0.85))
        confidence = float(np.clip(0.52 + min(0.25, (peak_z - z_thresh) * 0.025), 0.52, 0.78))
        detail = (
            f"Page {page_idx}: detected {len(boxes)} localized JPEG error-level outlier(s) "
            f"(peak z={peak_z:.1f}, median block ELA={med_ela:.2f}, MAD={mad_ela:.2f})."
        )
        return score, confidence, "suspicious", boxes, detail

    global_p95 = float(np.percentile(local_blk_ela, 95))
    score = float(np.clip((global_p95 - med_ela) / 40.0, 0.0, 0.18))
    confidence = 0.65
    detail = (
        f"Page {page_idx}: error levels appear spatially consistent "
        f"(median block ELA={med_ela:.2f}, p95={global_p95:.2f})."
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
