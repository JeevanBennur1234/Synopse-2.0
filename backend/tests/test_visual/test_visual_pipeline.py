from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from app.detectors.visual import VisualForensicsDetector, analyze
from app.schemas import DetectorResult


class _ExplodingDetector:
    name = "exploding_mock"

    def analyze(
        self, source: Path, pages: list[Path], fields: dict[str, Any]
    ) -> list[DetectorResult]:
        raise RuntimeError("simulated internal failure")


def test_visual_entry_point_runs_all_detectors_on_jpeg(tmp_path: Path) -> None:
    jpg = tmp_path / "doc.jpg"
    img = Image.new("RGB", (500, 600), color=(242, 242, 242))
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "KAVACH UNIFIED PIPELINE TEST", fill=(20, 20, 20))
    img.save(jpg, format="JPEG", quality=90)

    results = analyze(jpg, [jpg], {"invoice_no": "INV-001"})
    names = [r.name for r in results]
    assert names == ["ela", "copy_move", "noise_inconsistency", "image_metadata"]
    assert all(isinstance(r, DetectorResult) for r in results)


def test_visual_entry_point_handles_multipage_pdf(tmp_path: Path) -> None:
    p0 = tmp_path / "p0.png"
    p1 = tmp_path / "p1.png"
    for idx, p in enumerate((p0, p1)):
        img = Image.new("RGB", (500, 600), color=(245, 245, 245))
        ImageDraw.Draw(img).text((50, 50), f"PDF Page {idx}", fill=(10, 10, 10))
        img.save(p, format="PNG")

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    results = analyze(pdf, [p0, p1], {})
    by_name = {r.name: r for r in results}
    assert by_name["ela"].status == "not_applicable"
    assert by_name["image_metadata"].status == "not_applicable"
    assert len(results) == 4


def test_visual_pipeline_isolates_detector_failure(tmp_path: Path) -> None:
    png = tmp_path / "doc.png"
    Image.new("RGB", (300, 300), color=(230, 230, 230)).save(png)

    pipeline = VisualForensicsDetector(
        detectors=[_ExplodingDetector(), *VisualForensicsDetector()._detectors]
    )
    results = pipeline.analyze(png, [png], {})
    assert len(results) == 5
    assert results[0].name == "exploding_mock"
    assert results[0].status == "error"
    assert "simulated internal failure" in results[0].evidence
    # Remaining detectors still ran normally
    assert results[1].name == "ela"
    assert results[1].status == "not_applicable"
