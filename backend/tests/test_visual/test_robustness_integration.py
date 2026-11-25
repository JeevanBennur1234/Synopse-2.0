"""Integration compatibility and robustness tests for the visual forensics pipeline."""

from __future__ import annotations

import hashlib
import random
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.detectors.visual import analyze
from app.schemas import DetectorResult


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _det_noise(shape: tuple[int, int], seed: int, amp: int) -> np.ndarray:
    rng = random.Random(seed)
    h, w = shape
    vals = [rng.randint(-amp, amp) for _ in range(h * w)]
    return np.array(vals, dtype=np.int16).reshape((h, w))


def _assert_contract(results: list[DetectorResult], page_sizes: list[tuple[int, int]]) -> None:
    assert len(results) == 5
    for r in results:
        assert isinstance(r, DetectorResult)
        assert 0.0 <= r.score <= 1.0
        assert 0.0 <= r.confidence <= 1.0
        assert r.status in {"passed", "suspicious", "inconclusive", "not_applicable", "error"}
        for box in r.boxes:
            assert 0 <= box.page < len(page_sizes)
            pw, ph = page_sizes[box.page]
            assert 0 <= box.x < pw
            assert 0 <= box.y < ph
            assert box.w > 0 and box.h > 0
            assert box.x + box.w <= pw
            assert box.y + box.h <= ph


def test_integration_contract_and_immutability(tmp_path: Path) -> None:
    src = tmp_path / "invoice.jpg"
    page = tmp_path / "page_0.png"

    bg = np.clip(244 + _det_noise((900, 700), 11, 2), 0, 255).astype(np.uint8)
    img = Image.fromarray(np.repeat(bg[:, :, None], 3, axis=2), mode="RGB")
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "KAVACH INTEGRATION TEST INVOICE", fill=(15, 15, 15))
    img.save(src, format="JPEG", quality=90)
    img.save(page, format="PNG")

    src_hash = _sha256(src)
    page_hash = _sha256(page)
    fields = {"invoice_number": ["INV-2026-01"], "total": ["45000.00"]}

    results = analyze(src, [page], fields)
    _assert_contract(results, [(700, 900)])
    assert _sha256(src) == src_hash
    assert _sha256(page) == page_hash


def test_robustness_repeated_table_rows_and_logos(tmp_path: Path) -> None:
    # 1. Clean invoice with 14 repeated table rows
    rows_page = tmp_path / "repeated_rows.png"
    bg = np.clip(245 + _det_noise((1000, 800), 21, 2), 0, 255).astype(np.uint8)
    img = Image.fromarray(np.repeat(bg[:, :, None], 3, axis=2), mode="RGB")
    draw = ImageDraw.Draw(img)
    draw.text((50, 40), "INVOICE - REPEATED TABLE ROWS", fill=(10, 10, 10))
    for i in range(14):
        y = 110 + i * 55
        draw.rectangle([45, y - 6, 755, y + 32], outline=(180, 180, 180), width=1)
        draw.text((60, y), f"Item {i + 1:02d}  Service Fee  Qty 1  Rs. 1,250.00", fill=(20, 20, 20))
    img.save(rows_page, format="PNG")

    res_rows = analyze(rows_page, [rows_page], {})
    _assert_contract(res_rows, [(800, 1000)])
    by_name = {r.name: r for r in res_rows}
    assert by_name["copy_move"].status == "passed"
    assert by_name["noise_inconsistency"].status == "passed"

    # 2. Document with a repeated company logo (header + footer)
    logo_page = tmp_path / "repeated_logo.png"
    logo_img = img.copy()
    logo = Image.new("RGB", (140, 80), color=(240, 245, 255))
    ldraw = ImageDraw.Draw(logo)
    ldraw.rectangle([3, 3, 136, 76], outline=(20, 60, 160), width=3)
    ldraw.ellipse([10, 10, 50, 50], outline=(200, 40, 40), width=3)
    ldraw.text((58, 24), "KAVACH", fill=(20, 60, 160))
    ldraw.text((14, 58), "TRUSTED CORP", fill=(30, 30, 30))
    logo_img.paste(logo, (600, 20))
    logo_img.paste(logo, (600, 900))
    logo_img.save(logo_page, format="PNG")

    res_logos = analyze(logo_page, [logo_page], {})
    _assert_contract(res_logos, [(800, 1000)])


def test_robustness_scanned_low_res_and_jpeg_qualities(tmp_path: Path) -> None:
    # 1. Clean simulated scanned document
    scan_path = tmp_path / "clean_scan.png"
    scan_noise = _det_noise((900, 700), 33, 5)
    scan_arr = np.clip(236 + scan_noise, 0, 255).astype(np.uint8)
    scan_img = Image.fromarray(np.repeat(scan_arr[:, :, None], 3, axis=2), mode="RGB")
    sdraw = ImageDraw.Draw(scan_img)
    sdraw.text((50, 50), "SCANNED RECEIPT #991", fill=(30, 30, 30))
    for i in range(6):
        sdraw.text((50, 130 + i * 65), f"Entry {i + 1}: Office Supplies Rs. {(i + 1) * 320}", fill=(35, 35, 35))
    scan_img.save(scan_path, format="PNG")

    res_scan = analyze(scan_path, [scan_path], {})
    _assert_contract(res_scan, [(700, 900)])
    assert {r.name: r for r in res_scan}["noise_inconsistency"].status == "passed"

    # 2. Low-resolution document (200x260)
    low_res = tmp_path / "low_res.jpg"
    scan_img.resize((200, 260), Image.Resampling.BILINEAR).save(low_res, format="JPEG", quality=75)
    res_low = analyze(low_res, [low_res], {})
    _assert_contract(res_low, [(200, 260)])

    # 3. Clean JPEGs at qualities 50, 75, 95
    for q in (50, 75, 95):
        qp = tmp_path / f"clean_q{q}.jpg"
        scan_img.save(qp, format="JPEG", quality=q)
        res_q = analyze(qp, [qp], {})
        _assert_contract(res_q, [(700, 900)])


def test_robustness_tampered_multipage_and_timing(tmp_path: Path) -> None:
    p0 = tmp_path / "page_0.png"
    p1 = tmp_path / "page_1.png"

    bg = np.clip(242 + _det_noise((960, 768), 55, 3), 0, 255).astype(np.uint8)
    clean_img = Image.fromarray(np.repeat(bg[:, :, None], 3, axis=2), mode="RGB")
    ImageDraw.Draw(clean_img).text((50, 50), "MULTI-PAGE DOC PAGE 0", fill=(20, 20, 20))
    clean_img.save(p0, format="PNG")

    tampered_arr = np.asarray(clean_img, dtype=np.uint8).copy()
    patch_noise = _det_noise((144, 144), 77, 24)
    patch = np.clip(240 + patch_noise, 0, 255).astype(np.uint8)
    tampered_arr[500:644, 400:544] = np.repeat(patch[:, :, None], 3, axis=2)
    Image.fromarray(tampered_arr, mode="RGB").save(p1, format="PNG")

    pdf_src = tmp_path / "multi.pdf"
    pdf_src.write_bytes(b"%PDF-1.4\n")

    t0 = time.perf_counter()
    results = analyze(pdf_src, [p0, p1], {})
    elapsed = time.perf_counter() - t0
    _assert_contract(results, [(768, 960), (768, 960)])
    by_name = {r.name: r for r in results}
    assert by_name["noise_inconsistency"].status == "suspicious"
    assert all(b.page == 1 for b in by_name["noise_inconsistency"].boxes)
    assert elapsed < 10.0
