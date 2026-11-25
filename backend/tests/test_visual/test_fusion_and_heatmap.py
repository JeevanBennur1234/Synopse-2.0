from pathlib import Path

from PIL import Image

from app.detectors.visual.evidence_fusion import compute_iou, correlate_evidence
from app.detectors.visual.heatmap import render_multipage_overlays, render_page_overlay
from app.schemas import BoundingBox, DetectorResult


def test_evidence_fusion_groups_overlapping_detectors_without_mutating_scores() -> None:
    r1 = DetectorResult(
        name="ela",
        score=0.55,
        confidence=0.65,
        status="suspicious",
        evidence="ELA outlier",
        boxes=[BoundingBox(page=0, x=100, y=200, w=120, h=40)],
    )
    r2 = DetectorResult(
        name="noise_inconsistency",
        score=0.62,
        confidence=0.70,
        status="suspicious",
        evidence="Noise outlier",
        boxes=[BoundingBox(page=0, x=110, y=205, w=115, h=38)],
    )
    r3 = DetectorResult(
        name="typography",
        score=0.45,
        confidence=0.55,
        status="suspicious",
        evidence="Different page region",
        boxes=[BoundingBox(page=1, x=50, y=50, w=80, h=20)],
    )

    assert compute_iou(r1.boxes[0], r2.boxes[0]) > 0.5
    assert compute_iou(r1.boxes[0], r3.boxes[0]) == 0.0

    report = correlate_evidence([r1, r2, r3])
    assert report.original_results == [r1, r2, r3]
    assert report.corroborated_count == 1
    assert len(report.regions) == 2
    p0_region = next(reg for reg in report.regions if reg.page == 0)
    assert p0_region.corroborated is True
    assert p0_region.detectors == ("ela", "noise_inconsistency")


def test_heatmap_renders_individual_combined_and_side_by_side(tmp_path: Path) -> None:
    p0 = tmp_path / "p0.png"
    p1 = tmp_path / "p1.png"
    Image.new("RGB", (400, 500), color=(245, 245, 245)).save(p0)
    Image.new("RGB", (400, 500), color=(245, 245, 245)).save(p1)

    results = [
        DetectorResult(
            name="ela",
            score=0.55,
            confidence=0.65,
            status="suspicious",
            evidence="ELA",
            boxes=[BoundingBox(page=0, x=40, y=40, w=100, h=40)],
        ),
        DetectorResult(
            name="noise_inconsistency",
            score=0.60,
            confidence=0.68,
            status="suspicious",
            evidence="Noise",
            boxes=[BoundingBox(page=0, x=45, y=42, w=95, h=38)],
        ),
    ]

    single = render_page_overlay(p0, 0, results, detector_filter={"ela"}, include_combined=False)
    assert single.size == (400, 500)

    side = render_page_overlay(p0, 0, results, side_by_side_original=True)
    assert side.size == (800, 500)

    multi = render_multipage_overlays([p0, p1], results)
    assert len(multi) == 2
