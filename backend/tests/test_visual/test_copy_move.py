from pathlib import Path

from PIL import Image, ImageDraw

from app.detectors.visual.copy_move import CopyMoveDetector
from app.schemas import DetectorResult


def _draw_textured_stamp(width: int = 160, height: int = 100) -> Image.Image:
    """Create a rich, textured synthetic stamp/badge for copy-move testing."""
    stamp = Image.new("RGB", (width, height), color=(248, 248, 250))
    draw = ImageDraw.Draw(stamp)
    draw.rectangle([4, 4, width - 5, height - 5], outline=(20, 40, 120), width=3)
    draw.ellipse([14, 14, 74, 74], outline=(160, 30, 30), width=3)
    draw.line([(14, 14), (74, 74)], fill=(160, 30, 30), width=2)
    draw.line([(74, 14), (14, 74)], fill=(160, 30, 30), width=2)
    draw.text((82, 22), "APPROVED", fill=(20, 40, 120))
    draw.text((82, 46), "REF #8472", fill=(30, 30, 30))
    draw.text((20, 80), "KAVACH-VERIFIED", fill=(40, 40, 40))
    return stamp


def _make_clean_document(path: Path, width: int = 900, height: int = 1100) -> Image.Image:
    img = Image.new("RGB", (width, height), color=(246, 246, 246))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, width - 40, 130], outline=(30, 30, 30), width=2)
    draw.text((60, 75), "SYNTHETIC COMMERCIAL INVOICE #2026-01", fill=(15, 15, 15))
    for i in range(10):
        y = 180 + i * 55
        draw.text((60, y), f"Line {i + 1}: Unique SKU-{1000 + i * 37}  Qty {i + 1}  Amt {(i + 1) * 450}", fill=(25, 25, 25))
    stamp = _draw_textured_stamp()
    img.paste(stamp, (620, 820))
    img.save(path, format="PNG")
    return img


def test_copy_move_clean_document(tmp_path: Path) -> None:
    clean_path = tmp_path / "clean.png"
    _make_clean_document(clean_path)

    res = CopyMoveDetector().analyze(clean_path, [clean_path], {})[0]
    assert isinstance(res, DetectorResult)
    assert res.name == "copy_move"
    assert res.status == "passed"
    assert res.score < 0.3
    assert res.boxes == []


def test_copy_move_detects_duplicated_region(tmp_path: Path) -> None:
    doc_path = tmp_path / "copymove.png"
    img = _make_clean_document(doc_path)
    # Duplicate the textured stamp from (620, 820) to (120, 820)
    stamp = img.crop((620, 820, 780, 920))
    img.paste(stamp, (120, 820))
    img.save(doc_path, format="PNG")

    res = CopyMoveDetector().analyze(doc_path, [doc_path], {})[0]
    assert res.status == "suspicious"
    assert 0.40 <= res.score <= 0.80
    assert len(res.boxes) >= 2
    # Check that both original and duplicated stamp areas are covered
    left_hit = any(b.x < 280 and b.x + b.w > 120 and b.y < 920 and b.y + b.h > 820 for b in res.boxes)
    right_hit = any(b.x < 780 and b.x + b.w > 620 and b.y < 920 and b.y + b.h > 820 for b in res.boxes)
    assert left_hit and right_hit


def test_copy_move_repeated_header_footer_logo_is_inconclusive(tmp_path: Path) -> None:
    logo_doc = tmp_path / "repeated_logo.png"
    img = _make_clean_document(logo_doc)
    logo = Image.new("RGB", (150, 90), color=(240, 246, 255))
    ldraw = ImageDraw.Draw(logo)
    ldraw.rectangle([3, 3, 146, 86], outline=(15, 70, 140), width=3)
    ldraw.polygon([(20, 70), (45, 20), (70, 70)], outline=(15, 70, 140), width=2)
    ldraw.text((78, 28), "ACME", fill=(15, 70, 140))
    ldraw.text((78, 50), "CORP", fill=(40, 40, 40))
    # Place identical company logo in header (top margin) and footer (bottom margin)
    img.paste(logo, (680, 30))
    img.paste(logo, (680, 960))
    img.save(logo_doc, format="PNG")

    res = CopyMoveDetector().analyze(logo_doc, [logo_doc], {})[0]
    assert res.status in {"passed", "inconclusive"}
    assert res.score <= 0.30


def test_copy_move_multipage_pdf_pages(tmp_path: Path) -> None:
    p0 = tmp_path / "page_0.png"
    p1 = tmp_path / "page_1.png"
    _make_clean_document(p0)
    img1 = _make_clean_document(p1)
    stamp = img1.crop((620, 820, 780, 920))
    img1.paste(stamp, (140, 780))
    img1.save(p1, format="PNG")

    pdf_src = tmp_path / "multi.pdf"
    pdf_src.write_bytes(b"%PDF-1.4\n")

    res = CopyMoveDetector().analyze(pdf_src, [p0, p1], {})[0]
    assert res.status == "suspicious"
    assert all(b.page == 1 for b in res.boxes)


def test_copy_move_blank_and_invalid(tmp_path: Path) -> None:
    blank = tmp_path / "blank.png"
    Image.new("RGB", (400, 400), color=(255, 255, 255)).save(blank)
    res_blank = CopyMoveDetector().analyze(blank, [blank], {})[0]
    assert res_blank.status == "inconclusive"

    res_missing = CopyMoveDetector().analyze(tmp_path / "missing.png", [], {})[0]
    assert res_missing.status == "error"
