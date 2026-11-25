"""Local noise inconsistency detector for business documents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import cv2
from PIL import Image

from app.schemas import BoundingBox, DetectorResult

MIN_IMAGE_DIM = 128
BLOCK_SIZE = 48
EDGE_GRAD_THRESH = 60.0
MIN_NON_EDGE_RATIO = 0.35
Z_THRESH = 4.5
MIN_ABS_NOISE_DIFF = 1.8
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _clamp_box(
    x: int, y: int, w: int, h: int, page_w: int, page_h: int, page_idx: int
) -> BoundingBox | None:
    x1 = max(0, min(x, page_w - 1))
    y1 = max(0, min(y, page_h - 1))
    x2 = max(x1 + 1, min(x + w, page_w))
    y2 = max(y1 + 1, min(y + h, page_h))
    if x2 <= x1 or y2 <= y1:
        return None
    return BoundingBox(page=page_idx, x=x1, y=y1, w=x2 - x1, h=y2 - y1)


def _analyze_page(
    page_path: Path, page_idx: int
) -> tuple[str, float, float, list[BoundingBox], str]:
    """Measure local background noise consistency while masking out normal text edges."""
    with Image.open(page_path) as pil_img:
        gray = np.asarray(pil_img.convert("L"), dtype=np.float32)

    orig_h, orig_w = gray.shape[:2]
    if orig_h < MIN_IMAGE_DIM or orig_w < MIN_IMAGE_DIM:
        return (
            "inconclusive",
            0.0,
            0.1,
            [],
            f"Page {page_idx}: image too small ({orig_w}x{orig_h}) for regional noise analysis.",
        )

    if float(np.std(gray)) < 1.5:
        return (
            "inconclusive",
            0.0,
            0.1,
            [],
            f"Page {page_idx}: blank or uniform image; noise analysis is inconclusive.",
        )

    # High-pass noise residual via median filter subtraction
    denoised = cv2.medianBlur(gray.astype(np.uint8), 3).astype(np.float32)
    residual = gray - denoised

    # Mask out sharp structural edges (text/table lines) using a lightly smoothed image
    # so high-frequency pixel noise is not mistaken for structural edges.
    blurred_for_edges = cv2.GaussianBlur(gray, (5, 5), 1.0)
    gx = cv2.Sobel(blurred_for_edges, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blurred_for_edges, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = np.sqrt(gx * gx + gy * gy)
    edge_mask = (grad_mag > EDGE_GRAD_THRESH).astype(np.uint8)
    edge_mask = cv2.dilate(edge_mask, np.ones((5, 5), dtype=np.uint8), iterations=1)
    smooth_mask = edge_mask == 0

    rows = orig_h // BLOCK_SIZE
    cols = orig_w // BLOCK_SIZE
    if rows < 2 or cols < 2:
        return (
            "inconclusive",
            0.0,
            0.15,
            [],
            f"Page {page_idx}: too few blocks ({rows}x{cols}) for noise comparison.",
        )

    noise_grid = np.full((rows, cols), np.nan, dtype=np.float32)
    for r in range(rows):
        y0, y1 = r * BLOCK_SIZE, (r + 1) * BLOCK_SIZE
        for c in range(cols):
            x0, x1 = c * BLOCK_SIZE, (c + 1) * BLOCK_SIZE
            valid = smooth_mask[y0:y1, x0:x1]
            if float(np.mean(valid)) < MIN_NON_EDGE_RATIO:
                continue
            vals = residual[y0:y1, x0:x1][valid]
            med = float(np.median(vals))
            mad = float(np.median(np.abs(vals - med)))
            # Robust sigma estimate; fallback to std if MAD is 0 on quantized data
            sigma = 1.4826 * mad
            if sigma < 1e-3:
                sigma = float(np.std(vals))
            noise_grid[r, c] = sigma

    valid_blocks = noise_grid[~np.isnan(noise_grid)]
    if valid_blocks.size < 4:
        return (
            "inconclusive",
            0.0,
            0.2,
            [],
            f"Page {page_idx}: insufficient non-edge background blocks for reliable noise baseline.",
        )

    med_noise = float(np.median(valid_blocks))
    mad_noise = float(np.median(np.abs(valid_blocks - med_noise)))
    scale = max(1.4826 * mad_noise, 0.35)

    # Identify blocks with strong noise deviation (either much noisier or suspiciously smoothed)
    outlier_grid = np.zeros((rows, cols), dtype=np.uint8)
    z_grid = np.zeros((rows, cols), dtype=np.float32)

    for r in range(rows):
        for c in range(cols):
            val = noise_grid[r, c]
            if np.isnan(val):
                continue
            diff = abs(float(val) - med_noise)
            z = diff / scale
            z_grid[r, c] = z
            if z > Z_THRESH and diff > MIN_ABS_NOISE_DIFF:
                outlier_grid[r, c] = 1

    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(outlier_grid, connectivity=8)
    boxes: list[BoundingBox] = []
    peak_z = 0.0
    flagged_blocks = 0

    for label_idx in range(1, num_labels):
        bx, by, bw, bh, area = stats[label_idx]
        # Require at least 2x1 or 2-block cluster OR a very strong single-block outlier (z > 7)
        local_peak = float(np.max(z_grid[by : by + bh, bx : bx + bw]))
        if area == 1 and local_peak < 7.0:
            continue
        if area > int(0.45 * rows * cols):
            continue
        peak_z = max(peak_z, local_peak)
        flagged_blocks += int(area)
        clamped = _clamp_box(
            int(bx * BLOCK_SIZE),
            int(by * BLOCK_SIZE),
            int(bw * BLOCK_SIZE),
            int(bh * BLOCK_SIZE),
            orig_w,
            orig_h,
            page_idx,
        )
        if clamped is not None:
            boxes.append(clamped)

    if boxes:
        raw_score = 0.40 + min(0.25, (peak_z - Z_THRESH) * 0.03) + min(
            0.15, (flagged_blocks / float(valid_blocks.size)) * 1.5
        )
        score = float(np.clip(raw_score, 0.35, 0.80))
        confidence = float(np.clip(0.50 + min(0.25, (peak_z - Z_THRESH) * 0.03), 0.50, 0.78))
        detail = (
            f"Page {page_idx}: detected {len(boxes)} region(s) with anomalous background noise "
            f"(baseline sigma={med_noise:.2f}, peak z={peak_z:.1f}; text edges excluded)."
        )
        return "suspicious", score, confidence, boxes, detail

    p95 = float(np.percentile(valid_blocks, 95))
    score = float(np.clip((p95 - med_noise) / 15.0, 0.0, 0.18))
    detail = (
        f"Page {page_idx}: background noise is consistent across {valid_blocks.size} blocks "
        f"(median sigma={med_noise:.2f}, p95={p95:.2f}; text edges excluded)."
    )
    return "passed", score, 0.65, [], detail


class NoiseInconsistencyDetector:
    """Regional noise inconsistency detector implementing the shared Detector protocol."""

    name = "noise_inconsistency"

    def analyze(
        self, source: Path, pages: list[Path], fields: dict[str, Any]
    ) -> list[DetectorResult]:
        target_pages = list(pages) if pages else []
        if not target_pages:
            try:
                src = Path(source)
                if src.exists() and src.is_file() and src.suffix.lower() in IMAGE_EXTENSIONS:
                    target_pages = [src]
            except TypeError:
                target_pages = []

        if not target_pages:
            return [
                DetectorResult(
                    name=self.name,
                    score=0.0,
                    confidence=0.0,
                    status="error",
                    evidence="No rendered page images available for noise inconsistency analysis.",
                    boxes=[],
                )
            ]

        all_boxes: list[BoundingBox] = []
        details: list[str] = []
        max_score = 0.0
        confidences: list[float] = []
        statuses: list[str] = []

        for idx, page_path in enumerate(target_pages):
            try:
                p = Path(page_path)
                if not p.exists() or not p.is_file():
                    statuses.append("error")
                    details.append(f"Page {idx}: file missing ({p.name}).")
                    continue
                status, score, conf, boxes, detail = _analyze_page(p, idx)
                statuses.append(status)
                max_score = max(max_score, score)
                confidences.append(conf)
                all_boxes.extend(boxes)
                details.append(detail)
            except Exception as exc:
                statuses.append("error")
                details.append(f"Page {idx}: noise analysis failed ({exc}).")

        if "suspicious" in statuses:
            final_status = "suspicious"
        elif "passed" in statuses:
            final_status = "passed"
        elif "inconclusive" in statuses:
            final_status = "inconclusive"
        else:
            final_status = "error"

        final_conf = float(np.mean(confidences)) if confidences else 0.0
        return [
            DetectorResult(
                name=self.name,
                score=round(max_score, 4),
                confidence=round(final_conf, 4),
                status=final_status,
                evidence=" ".join(details),
                boxes=all_boxes,
            )
        ]


def analyze(
    source: Path, pages: list[Path], fields: dict[str, Any]
) -> list[DetectorResult]:
    """Module-level entry point matching the Detector protocol."""
    return NoiseInconsistencyDetector().analyze(source, pages, fields)
