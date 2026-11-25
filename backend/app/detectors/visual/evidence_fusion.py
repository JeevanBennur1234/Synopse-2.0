"""Multi-detector spatial evidence correlation (non-scoring, read-only).

Preserves original DetectorResult objects without altering scores, confidences,
or shared risk scoring. Groups overlapping bounding boxes across detectors on the
same page so correlated visual signals are not mistaken for independent proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import BoundingBox, DetectorResult


@dataclass(frozen=True)
class CorrelatedRegion:
    """A spatial region where one or more detectors reported bounding boxes."""

    page: int
    box: BoundingBox
    detectors: tuple[str, ...]
    max_iou: float
    corroborated: bool
    summary: str


@dataclass(frozen=True)
class EvidenceCorrelationReport:
    """Structured correlation output preserving original detector results."""

    original_results: list[DetectorResult]
    regions: list[CorrelatedRegion] = field(default_factory=list)
    corroborated_count: int = 0
    note: str = (
        "Overlapping visual detectors may reflect the same underlying artifact "
        "and are grouped for review rather than treated as independent confirmation."
    )


def compute_iou(a: BoundingBox, b: BoundingBox) -> float:
    """Compute Intersection-over-Union for two BoundingBox objects on the same page."""
    if a.page != b.page:
        return 0.0
    ix1 = max(a.x, b.x)
    iy1 = max(a.y, b.y)
    ix2 = min(a.x + a.w, b.x + b.w)
    iy2 = min(a.y + a.h, b.y + b.h)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = a.w * a.h + b.w * b.h - inter
    return float(inter / union) if union > 0 else 0.0


def _containment_ratio(a: BoundingBox, b: BoundingBox) -> float:
    """Return max(intersection / area(a), intersection / area(b)) for same-page boxes."""
    if a.page != b.page:
        return 0.0
    ix1 = max(a.x, b.x)
    iy1 = max(a.y, b.y)
    ix2 = min(a.x + a.w, b.x + b.w)
    iy2 = min(a.y + a.h, b.y + b.h)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    min_area = max(1, min(a.w * a.h, b.w * b.h))
    return float(inter / min_area)


def _merge_boxes(boxes: list[BoundingBox]) -> BoundingBox:
    page = boxes[0].page
    x1 = min(b.x for b in boxes)
    y1 = min(b.y for b in boxes)
    x2 = max(b.x + b.w for b in boxes)
    y2 = max(b.y + b.h for b in boxes)
    return BoundingBox(page=page, x=x1, y=y1, w=max(1, x2 - x1), h=max(1, y2 - y1))


def correlate_evidence(
    results: list[DetectorResult], iou_threshold: float = 0.20, containment_threshold: float = 0.50
) -> EvidenceCorrelationReport:
    """Group overlapping or contained boxes across detectors on each page.

    Does NOT mutate `results`, inflate scores, or add new scored DetectorResults.
    """
    items: list[tuple[str, BoundingBox]] = []
    for res in results:
        if res.status not in {"suspicious", "inconclusive"}:
            continue
        for box in res.boxes:
            items.append((res.name, box))

    n = len(items)
    visited = [False] * n
    regions: list[CorrelatedRegion] = []

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        queue = [i]
        group_indices = [i]
        max_pair_iou = 0.0

        while queue:
            curr = queue.pop()
            _, box_c = items[curr]
            for j in range(n):
                if visited[j]:
                    continue
                _, box_j = items[j]
                if box_c.page != box_j.page:
                    continue
                iou = compute_iou(box_c, box_j)
                contain = _containment_ratio(box_c, box_j)
                if iou >= iou_threshold or contain >= containment_threshold:
                    visited[j] = True
                    queue.append(j)
                    group_indices.append(j)
                    max_pair_iou = max(max_pair_iou, iou)

        group_boxes = [items[idx][1] for idx in group_indices]
        det_names = tuple(sorted({items[idx][0] for idx in group_indices}))
        merged = _merge_boxes(group_boxes)
        corroborated = len(det_names) >= 2
        summary = (
            f"Page {merged.page}: {'corroborated' if corroborated else 'single-detector'} "
            f"region ({merged.x},{merged.y},{merged.w}x{merged.h}) flagged by {', '.join(det_names)}."
        )
        regions.append(
            CorrelatedRegion(
                page=merged.page,
                box=merged,
                detectors=det_names,
                max_iou=round(max_pair_iou, 4),
                corroborated=corroborated,
                summary=summary,
            )
        )

    corroborated_count = sum(1 for r in regions if r.corroborated)
    return EvidenceCorrelationReport(
        original_results=list(results),
        regions=regions,
        corroborated_count=corroborated_count,
    )
