"""Multi-quality block-local Error Level Analysis (ELA) detector for JPEG documents."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from app.schemas import BoundingBox, DetectorResult

JPEG_EXTENSIONS = {".jpg", ".jpeg"}
RECOMPRESS_QUALITIES = (75, 90, 95)
QUALITY_WEIGHTS = (0.25, 0.40, 0.35)
DEFAULT_RECOMPRESS_QUALITY = 90
MIN_IMAGE_DIM = 64

NUMERIC_FIELD_KEYS = frozenset(
    {
        "total",
        "subtotal",
        "cgst",
        "sgst",
        "igst",
        "utgst",
        "cess",
        "discount",
        "opening_balance",
        "closing_balance",
        "tax_rate",
    }
)


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


def _compute_ela_map(
    rgb_image: np.ndarray, quality: int = DEFAULT_RECOMPRESS_QUALITY
) -> np.ndarray:
    """Recompress an RGB uint8 image as JPEG and return 2D luminance-weighted error map."""
    pil_img = Image.fromarray(rgb_image, mode="RGB")
    buffer = io.BytesIO()
    pil_img.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    with Image.open(buffer) as recomp_pil:
        recomp_rgb = np.asarray(recomp_pil.convert("RGB"), dtype=np.float32)

    diff = np.abs(rgb_image.astype(np.float32) - recomp_rgb)
    # Weight by luminance so 4:2:0 chroma subsampling on colored inks/stamps does not dominate.
    return 0.299 * diff[:, :, 0] + 0.587 * diff[:, :, 1] + 0.114 * diff[:, :, 2]


def _extract_numeric_boxes(
    fields: dict[str, Any], page_idx: int
) -> list[tuple[int, int, int, int]]:
    """Collect bounding boxes for OCR/extracted numeric fields on a page."""
    out: list[tuple[int, int, int, int]] = []
    if not isinstance(fields, dict):
        return out

    locations = fields.get("_field_locations")
    if isinstance(locations, dict):
        for key in NUMERIC_FIELD_KEYS:
            items = locations.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or item.get("page", 0) != page_idx:
                    continue
                bbox = item.get("bbox") or (
                    [item["x"], item["y"], item["w"], item["h"]]
                    if all(k in item for k in ("x", "y", "w", "h"))
                    else None
                )
                if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                    out.append(tuple(int(v) for v in bbox))  # type: ignore[arg-type]

    pages_meta = fields.get("_pages")
    if isinstance(pages_meta, list):
        for pg in pages_meta:
            if not isinstance(pg, dict) or pg.get("page") != page_idx:
                continue
            for word in pg.get("words", []):
                if not isinstance(word, dict):
                    continue
                text = str(word.get("text") or "")
                if any(ch.isdigit() for ch in text) and all(
                    k in word for k in ("x", "y", "w", "h")
                ):
                    out.append(
                        (int(word["x"]), int(word["y"]), int(word["w"]), int(word["h"]))
                    )
    return out


def _boxes_overlap(
    a: BoundingBox, b: tuple[int, int, int, int], margin: int = 8
) -> bool:
    bx, by, bw, bh = b
    return (
        a.x - margin < bx + bw
        and a.x + a.w + margin > bx
        and a.y - margin < by + bh
        and a.y + a.h + margin > by
    )


def _analyze_single_image(
    img_path: Path,
    page_idx: int,
    target_size: tuple[int, int] | None = None,
    fields: dict[str, Any] | None = None,
) -> tuple[float, float, str, list[BoundingBox], str]:
    """Run multi-quality block-local ELA on one JPEG and return (score, confidence, status, boxes, detail)."""
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

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    sat = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[:, :, 1].astype(np.float32)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = np.sqrt(grad_x * grad_x + grad_y * grad_y)

    block_size = max(16, min(32, min(orig_h, orig_w) // 16))
    rows_b, cols_b = orig_h // block_size, orig_w // block_size
    if rows_b < 3 or cols_b < 3:
        return (
            0.0,
            0.1,
            "inconclusive",
            [],
            f"Page {page_idx}: insufficient block grid ({cols_b}x{rows_b}) for block-local ELA.",
        )

    crop_h, crop_w = rows_b * block_size, cols_b * block_size
    b_grad = grad_mag[:crop_h, :crop_w].reshape(
        rows_b, block_size, cols_b, block_size
    ).mean(axis=(1, 3))
    b_sat = sat[:crop_h, :crop_w].reshape(
        rows_b, block_size, cols_b, block_size
    ).mean(axis=(1, 3))
    b_sat_frac = (sat[:crop_h, :crop_w] > 45.0).reshape(
        rows_b, block_size, cols_b, block_size
    ).mean(axis=(1, 3))

    # Suppress saturated graphic structures (colored stamps, seals, logos, banners) + 1-block halo.
    graphic_blocks = (b_sat > 20.0) | (b_sat_frac > 0.12)
    suppressed = (
        cv2.dilate(graphic_blocks.astype(np.uint8), np.ones((3, 3), dtype=np.uint8)) > 0
    )

    fit_mask = (~suppressed) & (b_grad > 2.0)
    if int(np.sum(fit_mask)) < 8:
        return (
            0.0,
            0.2,
            "inconclusive",
            [],
            f"Page {page_idx}: insufficient active low-saturation blocks ({int(np.sum(fit_mask))}) to establish a reliable ELA baseline.",
        )

    z_grids: list[np.ndarray] = []
    q90_map: np.ndarray | None = None

    for quality, weight in zip(RECOMPRESS_QUALITIES, QUALITY_WEIGHTS):
        ela_map = _compute_ela_map(rgb, quality=quality)
        if quality == 90:
            q90_map = ela_map
        b_ela = ela_map[:crop_h, :crop_w].reshape(
            rows_b, block_size, cols_b, block_size
        ).mean(axis=(1, 3))

        # Fit edge-error slope strictly on active low-saturation blocks so blank white areas
        # cannot collapse the slope to zero.
        slope = float(np.median(b_ela[fit_mask] / (b_grad[fit_mask] + 2.0)))
        residual = np.maximum(0.0, b_ela - 0.85 * slope * b_grad)

        # Measure each block relative to its 5x5 local neighborhood median.
        local_med = cv2.medianBlur(residual.astype(np.float32), 5)
        local_diff = residual - local_med

        valid_diff = local_diff[~suppressed] if np.any(~suppressed) else local_diff.ravel()
        med_d = float(np.median(valid_diff))
        mad_d = float(np.median(np.abs(valid_diff - med_d)))
        active_vals = residual[fit_mask] if int(np.sum(fit_mask)) >= 8 else valid_diff
        active_mad = float(np.median(np.abs(active_vals - float(np.median(active_vals)))))
        scale = max(1.4826 * mad_d, 1.4826 * active_mad, 0.25)

        z_q = (local_diff - med_d) / scale
        z_q[suppressed] = 0.0
        z_grids.append(weight * z_q)

    z_comb = sum(z_grids)
    z_thresh = 4.2
    anomaly_mask = (z_comb > z_thresh).astype(np.uint8)
    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(anomaly_mask, connectivity=8)

    page_w, page_h = target_size if target_size else (orig_w, orig_h)
    scale_x = page_w / orig_w
    scale_y = page_h / orig_h

    boxes: list[BoundingBox] = []
    peak_z = float(np.max(z_comb))
    flagged_peak_z = 0.0
    total_flagged_blocks = 0

    for label_idx in range(1, num_labels):
        bx, by, bw, bh, area = stats[label_idx]
        region_z = float(np.max(z_comb[by : by + bh, bx : bx + bw]))
        if area < 2 and region_z < 6.0:
            continue
        if area > int(0.45 * rows_b * cols_b):
            continue
        flagged_peak_z = max(flagged_peak_z, region_z)
        total_flagged_blocks += int(area)
        clamped = _clamp_box(
            int(round(bx * block_size * scale_x)),
            int(round(by * block_size * scale_y)),
            max(1, int(round(bw * block_size * scale_x))),
            max(1, int(round(bh * block_size * scale_y))),
            page_w,
            page_h,
            page_idx,
        )
        if clamped is not None:
            boxes.append(clamped)

    if boxes:
        area_ratio = total_flagged_blocks / float(rows_b * cols_b)
        raw_score = (
            0.42
            + min(0.28, (flagged_peak_z - z_thresh) * 0.04)
            + min(0.15, area_ratio * 2.0)
        )
        score = float(np.clip(raw_score, 0.35, 0.85))
        base_conf = float(
            np.clip(0.50 + min(0.22, (flagged_peak_z - z_thresh) * 0.03), 0.50, 0.72)
        )

        numeric_boxes = _extract_numeric_boxes(fields or {}, page_idx)
        overlap_note = ""
        if numeric_boxes:
            overlaps_numeric = any(
                _boxes_overlap(box, nbox) for box in boxes for nbox in numeric_boxes
            )
            if overlaps_numeric:
                confidence = min(0.82, base_conf + 0.10)
                overlap_note = " Flagged region overlaps extracted numeric field(s)."
            else:
                confidence = max(0.35, base_conf - 0.12)
                overlap_note = " Flagged region does not overlap extracted numeric fields."
        else:
            confidence = base_conf

        detail = (
            f"Page {page_idx}: detected {len(boxes)} localized multi-quality (75/90/95) JPEG "
            f"error-level outlier(s) (peak z={flagged_peak_z:.1f}; colored graphic regions suppressed)."
            f"{overlap_note}"
        )
        return score, confidence, "suspicious", boxes, detail

    zero_frac = float(np.mean(q90_map < 0.5)) if q90_map is not None else 1.0
    # Weak or zero-inflated evidence cannot establish clean authenticity; return inconclusive.
    if peak_z >= 1.5 or zero_frac >= 0.87:
        detail = (
            f"Page {page_idx}: JPEG ELA evidence is weak or zero-inflated "
            f"(peak local z={peak_z:.2f}, flat-zero ratio={zero_frac:.0%}); "
            "cannot distinguish subtle or globally re-saved splices from normal text quantization."
        )
        return 0.0, 0.25, "inconclusive", [], detail

    q90_med = float(np.median(q90_map)) if q90_map is not None else 0.0
    q90_p95 = float(np.percentile(q90_map, 95)) if q90_map is not None else 0.0
    score = float(np.clip((q90_p95 - q90_med) / 40.0, 0.0, 0.18))
    detail = (
        f"Page {page_idx}: multi-quality (75/90/95) error levels appear spatially consistent "
        f"(peak local z={peak_z:.2f}, Q90 median={q90_med:.2f}, p95={q90_p95:.2f})."
    )
    return score, 0.65, "passed", [], detail


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
                source_path, page_idx=0, target_size=target_size, fields=fields
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
