import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.detectors.visual.ela import ELADetector
from app.schemas import DetectorResult


def _deterministic_noise(shape: tuple[int, ...], seed: int, amplitude: int) -> np.ndarray:
    """Generate deterministic uint8-compatible int16 noise without numpy.random."""
    rng = random.Random(seed)
    total = 1
    for dim in shape:
        total *= dim
    vals = [rng.randint(-amplitude, amplitude) for _ in range(total)]
    return np.array(vals, dtype=np.int16).reshape(shape)


def _make_synthetic_invoice(path: Path, width: int = 800, height: int = 1000) -> Image.Image:
    """Create a synthetic document image with text-like lines and a clean background."""
    # Slight deterministic paper texture so background isn't mathematically zero-variance
    yy, xx = np.indices((height, width))
    texture = ((np.sin(xx * 0.37) + np.cos(yy * 0.41)) * 2.0).astype(np.int16)
    bg = np.clip(245 + texture[:, :, None], 0, 255).astype(np.uint8)
    bg = np.repeat(bg, 3, axis=2)
    img = Image.fromarray(bg, mode="RGB")
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, width - 40, 140], outline=(30, 30, 80), width=3)
    draw.text((60, 75), "KAVACH SYNTHETIC INVOICE #1042", fill=(20, 20, 20))
    for i in range(10):
        y = 200 + i * 50
        draw.text((60, y), f"Item {i + 1}: Consulting Services  Rs. {(i + 1) * 1500}.00", fill=(25, 25, 25))
    draw.text((60, 780), "TOTAL: Rs. 82,500.00", fill=(0, 0, 0))
    img.save(path, format="JPEG", quality=92)
    return img


def test_ela_clean_jpeg(tmp_path: Path) -> None:
    src = tmp_path / "clean_invoice.jpg"
    _make_synthetic_invoice(src)

    results = ELADetector().analyze(src, [src], {})
    assert len(results) == 1
    res = results[0]
    assert isinstance(res, DetectorResult)
    assert res.name == "ela"
    assert res.status == "passed"
    assert 0.0 <= res.score <= 0.3
    assert 0.0 <= res.confidence <= 1.0
    assert res.boxes == []


def test_ela_detects_synthetic_tampered_patch(tmp_path: Path) -> None:
    # Create base document saved at lower JPEG quality (e.g., 65)
    base_path = tmp_path / "base.jpg"
    _make_synthetic_invoice(base_path)
    with Image.open(base_path) as im:
        im.save(base_path, format="JPEG", quality=65)

    # Load base, paste a sharp high-quality synthetic patch (simulating local edit), save at quality=95
    tampered_path = tmp_path / "tampered_invoice.jpg"
    with Image.open(base_path) as base_im:
        tampered = base_im.copy()

    patch = Image.new("RGB", (220, 90), color=(250, 250, 250))
    pdraw = ImageDraw.Draw(patch)
    pdraw.rectangle([4, 4, 215, 85], outline=(10, 10, 10), width=2)
    pdraw.text((18, 30), "TOTAL: Rs. 999,999", fill=(180, 10, 10))
    # Add fine high-frequency noise/detail to the pasted patch so its JPEG error differs strongly
    patch_arr = np.asarray(patch, dtype=np.int16)
    noise = _deterministic_noise(patch_arr.shape, seed=7, amplitude=18)
    patch_arr = np.clip(patch_arr + noise, 0, 255).astype(np.uint8)
    patch = Image.fromarray(patch_arr, mode="RGB")

    tampered.paste(patch, (450, 740))
    tampered.save(tampered_path, format="JPEG", quality=96)

    results = ELADetector().analyze(tampered_path, [tampered_path], {})
    assert len(results) == 1
    res = results[0]
    assert res.status == "suspicious"
    assert 0.35 <= res.score <= 0.85
    assert len(res.boxes) >= 1
    # Verify at least one box overlaps the pasted region (450, 740, 220, 90)
    overlaps = any(
        (b.x < 670 and b.x + b.w > 450 and b.y < 830 and b.y + b.h > 740)
        for b in res.boxes
    )
    assert overlaps
    assert "does not alone prove forgery" in res.evidence.lower()


def test_ela_png_and_pdf_not_applicable(tmp_path: Path) -> None:
    png_path = tmp_path / "doc.png"
    Image.new("RGB", (400, 400), color=(240, 240, 240)).save(png_path, format="PNG")
    res_png = ELADetector().analyze(png_path, [png_path], {})[0]
    assert res_png.status == "not_applicable"
    assert res_png.score == 0.0
    assert res_png.confidence == 0.0

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    res_pdf = ELADetector().analyze(pdf_path, [png_path], {})[0]
    assert res_pdf.status == "not_applicable"
    assert res_pdf.score == 0.0


def test_ela_blank_and_invalid_input(tmp_path: Path) -> None:
    blank_path = tmp_path / "blank.jpg"
    Image.new("RGB", (300, 300), color=(255, 255, 255)).save(blank_path, format="JPEG")
    res_blank = ELADetector().analyze(blank_path, [blank_path], {})[0]
    assert res_blank.status == "inconclusive"

    missing_path = tmp_path / "does_not_exist.jpg"
    res_missing = ELADetector().analyze(missing_path, [], {})[0]
    assert res_missing.status == "error"

    corrupt_path = tmp_path / "corrupt.jpg"
    corrupt_path.write_bytes(b"not a real jpeg")
    res_corrupt = ELADetector().analyze(corrupt_path, [corrupt_path], {})[0]
    assert res_corrupt.status == "error"


def test_ela_suppresses_colored_stamp_false_positives(tmp_path: Path) -> None:
    src = tmp_path / "clean_with_stamp.jpg"
    img = _make_synthetic_invoice(src)
    draw = ImageDraw.Draw(img)
    # Draw a high-contrast colored circular stamp (typical false-positive source under naive RGB ELA)
    draw.ellipse([70, 740, 210, 880], outline=(20, 60, 180), width=5)
    draw.ellipse([82, 752, 198, 868], outline=(190, 30, 30), width=3)
    draw.text((100, 800), "APPROVED", fill=(20, 60, 180))
    img.save(src, format="JPEG", quality=92)

    res = ELADetector().analyze(src, [src], {})[0]
    assert res.status != "suspicious"
    assert res.boxes == []


def test_ela_adjusts_confidence_with_numeric_field_overlap(tmp_path: Path) -> None:
    base_path = tmp_path / "base.jpg"
    _make_synthetic_invoice(base_path)
    with Image.open(base_path) as im:
        im.save(base_path, format="JPEG", quality=65)

    tampered_path = tmp_path / "tampered_overlap.jpg"
    with Image.open(base_path) as base_im:
        tampered = base_im.copy()
    patch = Image.new("RGB", (220, 90), color=(250, 250, 250))
    pdraw = ImageDraw.Draw(patch)
    pdraw.rectangle([4, 4, 215, 85], outline=(10, 10, 10), width=2)
    pdraw.text((18, 30), "TOTAL: Rs. 999,999", fill=(20, 20, 20))
    patch_arr = np.asarray(patch, dtype=np.int16) + _deterministic_noise((90, 220, 3), seed=7, amplitude=18)
    tampered.paste(Image.fromarray(np.clip(patch_arr, 0, 255).astype(np.uint8), mode="RGB"), (450, 740))
    tampered.save(tampered_path, format="JPEG", quality=96)

    fields_hit = {"_field_locations": {"total": [{"page": 0, "bbox": [460, 755, 180, 50]}]}}
    fields_miss = {"_field_locations": {"total": [{"page": 0, "bbox": [60, 180, 120, 30]}]}}

    res_hit = ELADetector().analyze(tampered_path, [tampered_path], fields_hit)[0]
    res_miss = ELADetector().analyze(tampered_path, [tampered_path], fields_miss)[0]
    assert res_hit.status == "suspicious"
    assert res_miss.status == "suspicious"
    assert res_hit.confidence > res_miss.confidence


def test_ela_weak_zero_inflated_evidence_returns_inconclusive(tmp_path: Path) -> None:
    # 1. Sparse document with very few active text blocks
    sparse_white = tmp_path / "sparse_invoice.jpg"
    img = Image.new("RGB", (900, 1100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((80, 100), "INVOICE #100", fill=(20, 20, 20))
    draw.text((80, 200), "Grand total: 11,800.00", fill=(20, 20, 20))
    img.save(sparse_white, format="JPEG", quality=95)
    assert ELADetector().analyze(sparse_white, [sparse_white], {})[0].status == "inconclusive"

    # 2. Multi-line document on flat white background (zero-inflated background -> weak ELA)
    flat_white = tmp_path / "flat_invoice.jpg"
    img2 = Image.new("RGB", (900, 1100), color=(255, 255, 255))
    draw2 = ImageDraw.Draw(img2)
    for i in range(12):
        draw2.text((80, 80 + i * 70), f"Line {i + 1}: Consulting Service Fee  INR 1,000.00", fill=(20, 20, 20))
    img2.save(flat_white, format="JPEG", quality=95)
    assert ELADetector().analyze(flat_white, [flat_white], {})[0].status == "inconclusive"


def test_ela_benign_recompression_not_flagged(tmp_path: Path) -> None:
    orig = tmp_path / "orig.jpg"
    _make_synthetic_invoice(orig)
    for q in (60, 75, 95):
        recomp = tmp_path / f"recomp_{q}.jpg"
        with Image.open(orig) as im:
            im.save(recomp, format="JPEG", quality=q)
        res = ELADetector().analyze(recomp, [recomp], {})[0]
        # Weak compression evidence may legitimately be inconclusive.
        assert res.status in ("passed", "inconclusive")
        assert not res.boxes


def test_jpeg_aligned_pass_localizes_extra_invoice_splice():
    source = (
        Path(__file__).resolve().parents[3]
        / "dataset/eval_extra/tampered/extra_invoice_tampered_visual_ela_splice.jpg"
    )
    finding = ELADetector().analyze(source, [source], {})[0]
    assert finding.status == "suspicious"
    assert any(695 <= b.x < b.x + b.w <= 1170 and 954 <= b.y < b.y + b.h <= 1022
               for b in finding.boxes)
