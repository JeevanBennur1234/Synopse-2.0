from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.detectors.visual.typography import TypographyDetector
from app.schemas import DetectorResult


def _make_clean_mixed_style_invoice(path: Path) -> None:
    """Clean invoice with legitimate large heading, bold total, and consistent body lines."""
    img = Image.new("RGB", (800, 900), color=(250, 250, 250))
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    draw.text((50, 40), "TAX INVOICE - KAVACH CORP", fill=(15, 30, 90), font=font)
    for i in range(8):
        y = 140 + i * 60
        draw.text((50, y), f"Item {i + 1}  Consulting Service  Qty 1  Rs. 2,500.00", fill=(20, 20, 20), font=font)
    draw.text((50, 720), "GRAND TOTAL:  Rs. 20,000.00", fill=(0, 0, 0), font=font)
    img.save(path, format="PNG")


def test_typography_clean_mixed_styles_pass(tmp_path: Path) -> None:
    clean_path = tmp_path / "clean_typo.png"
    _make_clean_mixed_style_invoice(clean_path)

    res = TypographyDetector().analyze(clean_path, [clean_path], {})[0]
    assert isinstance(res, DetectorResult)
    assert res.name == "typography"
    assert res.status == "passed"
    assert res.score < 0.25
    assert res.boxes == []


def test_typography_detects_altered_amount_patch(tmp_path: Path) -> None:
    tampered_path = tmp_path / "tampered_typo.png"
    _make_clean_mixed_style_invoice(tampered_path)
    with Image.open(tampered_path) as im:
        img = im.copy()
    draw = ImageDraw.Draw(img)
    # Overwrite amount on the Grand Total line with shifted baseline, tinted background, and blue ink
    draw.rectangle([185, 708, 340, 742], fill=(210, 215, 225))
    draw.text((195, 712), "Rs. 99,999.00", fill=(180, 10, 10))
    img.save(tampered_path, format="PNG")

    res = TypographyDetector().analyze(tampered_path, [tampered_path], {})[0]
    assert res.status == "suspicious"
    assert 0.40 <= res.score <= 0.80
    assert len(res.boxes) >= 1
    assert any(b.x < 340 and b.x + b.w > 185 and b.y < 742 and b.y + b.h > 708 for b in res.boxes)


def test_typography_blank_and_invalid(tmp_path: Path) -> None:
    blank = tmp_path / "blank.png"
    Image.new("RGB", (300, 300), color=(255, 255, 255)).save(blank)
    assert TypographyDetector().analyze(blank, [blank], {})[0].status == "inconclusive"

    missing = tmp_path / "missing.png"
    assert TypographyDetector().analyze(missing, [], {})[0].status == "error"
