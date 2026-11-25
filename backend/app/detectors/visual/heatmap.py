"""Combined forensic visualization helpers (read-only over rendered pages)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import cv2
from PIL import Image, ImageDraw

from app.detectors.visual.evidence_fusion import correlate_evidence
from app.schemas import DetectorResult

DETECTOR_COLORS: dict[str, tuple[int, int, int]] = {
    "ela": (220, 50, 47),
    "copy_move": (211, 54, 130),
    "noise_inconsistency": (203, 75, 22),
    "typography": (38, 139, 210),
    "image_metadata": (108, 113, 196),
}


def render_page_overlay(
    page_path: Path,
    page_idx: int,
    results: list[DetectorResult],
    detector_filter: set[str] | None = None,
    include_combined: bool = True,
    side_by_side_original: bool = False,
) -> Image.Image:
    """Render an in-memory PIL overlay (or side-by-side comparison) for one page.

    Never modifies `page_path` on disk. Coordinates are in the rendered page pixel space.
    """
    with Image.open(page_path) as im:
        orig_img = im.convert("RGB")

    overlay_img = orig_img.copy()
    draw = ImageDraw.Draw(overlay_img, "RGBA")
    pw, ph = overlay_img.size

    # 1. Draw individual detector bounding boxes
    for res in results:
        if detector_filter is not None and res.name not in detector_filter:
            continue
        color = DETECTOR_COLORS.get(res.name, (181, 137, 0))
        for box in res.boxes:
            if box.page != page_idx:
                continue
            x1 = max(0, min(box.x, pw - 1))
            y1 = max(0, min(box.y, ph - 1))
            x2 = max(x1 + 1, min(box.x + box.w, pw))
            y2 = max(y1 + 1, min(box.y + box.h, ph))
            draw.rectangle([x1, y1, x2, y2], outline=(*color, 230), fill=(*color, 40), width=3)
            label = f"{res.name} ({res.score:.2f})"
            draw.text((x1 + 4, max(0, y1 - 14)), label, fill=(*color, 255))

    # 2. Draw combined corroborated regions if requested
    if include_combined:
        filtered = (
            [r for r in results if r.name in detector_filter]
            if detector_filter is not None
            else results
        )
        fusion = correlate_evidence(filtered)
        for region in fusion.regions:
            if region.page != page_idx or not region.corroborated:
                continue
            b = region.box
            x1 = max(0, min(b.x, pw - 1))
            y1 = max(0, min(b.y, ph - 1))
            x2 = max(x1 + 1, min(b.x + b.w, pw))
            y2 = max(y1 + 1, min(b.y + b.h, ph))
            draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0, 255), width=4)
            draw.text((x1 + 4, min(ph - 14, y2 + 2)), f"corroborated: {'+'.join(region.detectors)}", fill=(255, 0, 0, 255))

    if not side_by_side_original:
        return overlay_img

    combined = Image.new("RGB", (pw * 2, ph), color=(255, 255, 255))
    combined.paste(orig_img, (0, 0))
    combined.paste(overlay_img, (pw, 0))
    return combined


def render_multipage_overlays(
    pages: list[Path],
    results: list[DetectorResult],
    detector_filter: set[str] | None = None,
    include_combined: bool = True,
    side_by_side_original: bool = False,
) -> list[Image.Image]:
    """Render overlays across all zero-based pages."""
    return [
        render_page_overlay(
            page_path=p,
            page_idx=idx,
            results=results,
            detector_filter=detector_filter,
            include_combined=include_combined,
            side_by_side_original=side_by_side_original,
        )
        for idx, p in enumerate(pages)
    ]
