from pathlib import Path

from PIL import Image, PngImagePlugin

from app.detectors.image_metadata import ImageMetadataDetector
from app.schemas import DetectorResult


def test_metadata_missing_exif_is_inconclusive(tmp_path: Path) -> None:
    clean_jpg = tmp_path / "stripped.jpg"
    Image.new("RGB", (200, 200), color=(240, 240, 240)).save(clean_jpg, format="JPEG")

    res = ImageMetadataDetector().analyze(clean_jpg, [clean_jpg], {})[0]
    assert isinstance(res, DetectorResult)
    assert res.name == "image_metadata"
    assert res.status == "inconclusive"
    assert res.score == 0.0


def test_metadata_clean_camera_exif_passes(tmp_path: Path) -> None:
    jpg_path = tmp_path / "camera.jpg"
    img = Image.new("RGB", (200, 200), color=(240, 240, 240))
    exif = Image.Exif()
    exif[0x010F] = "Canon"  # Make
    exif[0x0110] = "EOS R6"  # Model
    exif[0x0132] = "2026:11:20 10:15:00"  # DateTime
    exif[0x9003] = "2026:11:20 10:15:00"  # DateTimeOriginal
    img.save(jpg_path, format="JPEG", exif=exif)

    res = ImageMetadataDetector().analyze(jpg_path, [jpg_path], {})[0]
    assert res.status == "passed"
    assert res.score < 0.2


def test_metadata_detects_editing_software_and_timestamp_mismatch(tmp_path: Path) -> None:
    edited_jpg = tmp_path / "edited.jpg"
    img = Image.new("RGB", (200, 200), color=(240, 240, 240))
    exif = Image.Exif()
    exif[0x0131] = "Adobe Photoshop 25.0 (Windows)"  # Software
    exif[0x0132] = "2026:11:25 14:00:00"  # DateTime
    exif[0x9003] = "2026:11:10 09:00:00"  # DateTimeOriginal (15 days earlier)
    img.save(edited_jpg, format="JPEG", exif=exif)

    res = ImageMetadataDetector().analyze(edited_jpg, [edited_jpg], {})[0]
    assert res.status == "suspicious"
    assert 0.35 <= res.score <= 0.80
    assert "photoshop" in res.evidence.lower()


def test_metadata_png_software_chunk(tmp_path: Path) -> None:
    edited_png = tmp_path / "edited.png"
    img = Image.new("RGB", (200, 200), color=(240, 240, 240))
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("Software", "GIMP 2.10.36")
    img.save(edited_png, format="PNG", pnginfo=pnginfo)

    res = ImageMetadataDetector().analyze(edited_png, [edited_png], {})[0]
    assert res.status == "suspicious"
    assert "gimp" in res.evidence.lower()


def test_metadata_pdf_is_not_applicable(tmp_path: Path) -> None:
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    res = ImageMetadataDetector().analyze(pdf_path, [], {})[0]
    assert res.status == "not_applicable"
    assert res.score == 0.0
