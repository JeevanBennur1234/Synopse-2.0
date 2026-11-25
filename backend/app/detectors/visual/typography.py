"""Typography tampering detector (native PDF font-span + visual line-level analysis)."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import cv2
from PIL import Image

from app.schemas import BoundingBox, DetectorResult

MIN_IMAGE_DIM = 128
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


def _analyze_pdf_spans(
    source_path: Path, page_sizes: list[tuple[int, int]]
) -> tuple[list[BoundingBox], list[str]]:
    """Inspect native PDF font spans per line for mixed fonts, sizes, or baseline shifts."""
    try:
        import fitz  # PyMuPDF
    except Exception:
        return [], []

    boxes: list[BoundingBox] = []
    notes: list[str] = []

    try:
        with fitz.open(source_path) as doc:
            for page_idx, page in enumerate(doc):
                if page_idx >= len(page_sizes):
                    break
                pw, ph = page_sizes[page_idx]
                sx = pw / max(1.0, float(page.rect.width))
                sy = ph / max(1.0, float(page.rect.height))

                text_dict = page.get_text("dict")
                for block in text_dict.get("blocks", []):
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        spans = [
                            s for s in line.get("spans", [])
                            if (s.get("text") or "").strip()
                        ]
                        if len(spans) < 2:
                            continue
                        # Skip lines with wide column gaps (e.g. left-aligned label + right-aligned total)
                        spans_sorted = sorted(spans, key=lambda s: float(s.get("bbox", [0, 0, 0, 0])[0]))
                        max_gap = max(
                            float(spans_sorted[k + 1]["bbox"][0]) - float(spans_sorted[k]["bbox"][2])
                            for k in range(len(spans_sorted) - 1)
                        )
                        if max_gap > 35.0:
                            continue

                        sizes = [float(s.get("size", 0.0)) for s in spans_sorted]
                        med_size = float(np.median(sizes))
                        origins = [float(s.get("origin", (0, 0))[1]) for s in spans_sorted]
                        med_origin = float(np.median(origins))
                        base_fonts = {
                            str(s.get("font", "")).split("-")[0].split(",")[0].lower()
                            for s in spans_sorted
                        }

                        for s in spans_sorted:
                            sz = float(s.get("size", 0.0))
                            oy = float(s.get("origin", (0, 0))[1])
                            size_diff = abs(sz - med_size)
                            base_diff = abs(oy - med_origin)
                            if size_diff >= 1.8 or base_diff >= 3.0 or len(base_fonts) >= 3:
                                bx0, by0, bx1, by1 = s.get("bbox", [0, 0, 0, 0])
                                clamped = _clamp_box(
                                    int(round(bx0 * sx)),
                                    int(round(by0 * sy)),
                                    max(1, int(round((bx1 - bx0) * sx))),
                                    max(1, int(round((by1 - by0) * sy))),
                                    pw,
                                    ph,
                                    page_idx,
                                )
                                if clamped is not None:
                                    boxes.append(clamped)
                                    notes.append(
                                        f"Page {page_idx}: PDF span '{s.get('text', '').strip()[:24]}' "
                                        f"differs in size/baseline/font within its line."
                                    )
    except Exception:
        return [], []

    return boxes, notes


def _analyze_page_visual(
    page_path: Path, page_idx: int
) -> tuple[str, float, float, list[BoundingBox], str]:
    """Compare word-level ink thickness, colour, baseline, spacing, and local background within each line."""
    with Image.open(page_path) as pil_img:
        rgb = np.asarray(pil_img.convert("RGB"), dtype=np.uint8)

    orig_h, orig_w = rgb.shape[:2]
    if orig_h < MIN_IMAGE_DIM or orig_w < MIN_IMAGE_DIM:
        return (
            "inconclusive",
            0.0,
            0.1,
            [],
            f"Page {page_idx}: image too small ({orig_w}x{orig_h}) for typography analysis.",
        )

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if float(np.std(gray)) < 2.0:
        return (
            "inconclusive",
            0.0,
            0.1,
            [],
            f"Page {page_idx}: blank or uniform image; typography analysis is inconclusive.",
        )

    # Adaptive dark-ink mask (handles slight lighting/scan gradients)
    ink = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 14
    )

    # Group characters into horizontal text lines
    line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (32, 3))
    line_mask = cv2.dilate(ink, line_kernel, iterations=1)
    n_lines, _, line_stats, _ = cv2.connectedComponentsWithStats(line_mask, connectivity=8)

    # Also group characters into words within each line
    word_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 3))
    word_mask = cv2.dilate(ink, word_kernel, iterations=1)

    boxes: list[BoundingBox] = []
    reasons: list[str] = []
    max_anomaly_strength = 0.0

    for l_idx in range(1, n_lines):
        lx, ly, lw, lh, l_area = line_stats[l_idx]
        # Skip non-text blocks, tall graphics/stamps, and thin borders
        if lw < 60 or lh < 10 or lh > 65 or l_area < 120:
            continue

        line_words = word_mask[ly : ly + lh, lx : lx + lw]
        n_words, _, w_stats, _ = cv2.connectedComponentsWithStats(line_words, connectivity=8)

        word_feats: list[dict[str, Any]] = []
        for w_idx in range(1, n_words):
            wx, wy, ww, wh, w_area = w_stats[w_idx]
            if ww < 14 or wh < 8 or wh > 55 or ww > int(0.45 * orig_w) or w_area < 30:
                continue
            gx, gy = lx + wx, ly + wy
            sub_ink = ink[gy : gy + wh, gx : gx + ww] > 0
            ink_count = int(np.sum(sub_ink))
            if ink_count < 12:
                continue

            # 1. Ink thickness proxy: fraction of bounding box filled + distance transform median
            dist = cv2.distanceTransform(sub_ink.astype(np.uint8), cv2.DIST_L2, 3)
            stroke_r = float(np.median(dist[sub_ink]))
            # 2. Ink colour (median RGB on ink pixels)
            ink_rgb = np.median(rgb[gy : gy + wh, gx : gx + ww][sub_ink], axis=0)
            # 3. Local background (non-ink pixels in padded ring around word)
            py0, py1 = max(0, gy - 4), min(orig_h, gy + wh + 4)
            px0, px1 = max(0, gx - 4), min(orig_w, gx + ww + 4)
            patch_gray = gray[py0:py1, px0:px1]
            patch_ink = ink[py0:py1, px0:px1] > 0
            bg_pixels = patch_gray[~patch_ink]
            local_bg = float(np.median(bg_pixels)) if bg_pixels.size >= 10 else 255.0

            word_feats.append(
                {
                    "box": (gx, gy, ww, wh),
                    "baseline": gy + wh,
                    "height": float(wh),
                    "stroke": stroke_r,
                    "rgb": ink_rgb,
                    "bg": local_bg,
                    "cx": gx + ww * 0.5,
                }
            )

        if len(word_feats) < 3:
            continue

        med_h = float(np.median([wf["height"] for wf in word_feats]))
        med_base = float(np.median([wf["baseline"] for wf in word_feats]))
        med_stroke = float(np.median([wf["stroke"] for wf in word_feats]))
        med_rgb = np.median(np.array([wf["rgb"] for wf in word_feats]), axis=0)
        med_bg = float(np.median([wf["bg"] for wf in word_feats]))

        for wf in word_feats:
            signals = 0
            detail_parts: list[str] = []

            # Local background patch shift (e.g. whiteout / pasted box)
            bg_diff = abs(wf["bg"] - med_bg)
            if bg_diff >= 18.0:
                signals += 2
                detail_parts.append(f"local background shift ({bg_diff:.0f})")

            # Colour shift within the same line
            rgb_diff = float(np.linalg.norm(wf["rgb"] - med_rgb))
            if rgb_diff >= 55.0:
                signals += 1
                detail_parts.append(f"ink colour shift (ΔRGB={rgb_diff:.0f})")

            # Baseline & height jump within the same line (count as one combined geometry cue)
            base_shift = abs(wf["baseline"] - med_base)
            h_ratio = abs(wf["height"] - med_h) / max(1.0, med_h)
            geom_flag = False
            if base_shift >= max(5.0, 0.32 * med_h):
                geom_flag = True
                detail_parts.append(f"baseline shift ({base_shift:.1f}px)")
            if h_ratio >= 0.45:
                geom_flag = True
                detail_parts.append(f"height mismatch ({h_ratio * 100:.0f}%)")
            if geom_flag:
                signals += 1

            # Stroke thickness jump (note: allow normal bold labels at start of line,
            # so only count stroke mismatch when paired with another cue or extreme jump)
            stroke_ratio = abs(wf["stroke"] - med_stroke) / max(0.5, med_stroke)
            if stroke_ratio >= 0.65:
                signals += 1
                detail_parts.append(f"stroke thickness diff ({stroke_ratio * 100:.0f}%)")

            # Require >= 2 corroborating typography signals to avoid flagging normal bold labels
            if signals >= 2:
                gx, gy, ww, wh = wf["box"]
                clamped = _clamp_box(gx, gy, ww, wh, orig_w, orig_h, page_idx)
                if clamped is not None:
                    boxes.append(clamped)
                    max_anomaly_strength = max(max_anomaly_strength, float(signals))
                    reasons.append(f"Page {page_idx}: " + ", ".join(detail_parts))

    if boxes:
        score = float(np.clip(0.42 + min(0.30, len(boxes) * 0.08) + (max_anomaly_strength - 2.0) * 0.06, 0.40, 0.80))
        confidence = float(np.clip(0.52 + min(0.22, (max_anomaly_strength - 2.0) * 0.07), 0.52, 0.76))
        summary = "; ".join(reasons[:3])
        return (
            "suspicious",
            score,
            confidence,
            boxes,
            f"{summary}. Note: typography anomalies indicate visual/layout inconsistency and do not alone prove forgery.",
        )

    return (
        "passed",
        0.04,
        0.65,
        [],
        f"Page {page_idx}: line-level typography, baseline, colour, and local backgrounds appear consistent.",
    )


class TypographyDetector:
    """Typography tampering detector implementing the shared Detector protocol."""

    name = "typography"

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
                    evidence="No rendered page images available for typography analysis.",
                    boxes=[],
                )
            ]

        all_boxes: list[BoundingBox] = []
        details: list[str] = []
        max_score = 0.0
        confidences: list[float] = []
        statuses: list[str] = []
        page_sizes: list[tuple[int, int]] = []

        for idx, page_path in enumerate(target_pages):
            try:
                p = Path(page_path)
                if not p.exists() or not p.is_file():
                    statuses.append("error")
                    details.append(f"Page {idx}: file missing ({p.name}).")
                    page_sizes.append((1, 1))
                    continue
                with Image.open(p) as im:
                    page_sizes.append(im.size)
                status, score, conf, boxes, detail = _analyze_page_visual(p, idx)
                statuses.append(status)
                max_score = max(max_score, score)
                confidences.append(conf)
                all_boxes.extend(boxes)
                details.append(detail)
            except Exception as exc:
                statuses.append("error")
                details.append(f"Page {idx}: typography analysis failed ({exc}).")
                page_sizes.append((1, 1))

        # Supplement with native PDF font-span analysis if source is a PDF
        try:
            src_path = Path(source)
            if src_path.exists() and src_path.suffix.lower() == ".pdf":
                pdf_boxes, pdf_notes = _analyze_pdf_spans(src_path, page_sizes)
                if pdf_boxes:
                    all_boxes.extend(pdf_boxes)
                    statuses.append("suspicious")
                    max_score = max(max_score, 0.58)
                    confidences.append(0.68)
                    details.extend(pdf_notes[:2])
        except Exception:
            pass

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
    return TypographyDetector().analyze(source, pages, fields)
