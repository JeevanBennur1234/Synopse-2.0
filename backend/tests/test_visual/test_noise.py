import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.detectors.visual.noise import NoiseInconsistencyDetector
from app.schemas import DetectorResult


def _deterministic_noise(shape: tuple[int, int], seed: int, amplitude: int) -> np.ndarray:
    rng = random.Random(seed)
    h, w = shape
    vals = [rng.randint(-amplitude, amplitude) for _ in range(h * w)]
    return np.array(vals, dtype=np.int16).reshape((h, w))


def _make_clean_noisy_doc(path: Path, width: int = 768, height: int = 960) -> np.ndarray:
    """Create a synthetic scanned-like document with uniform sensor noise and sharp text."""
    noise = _deterministic_noise((height, width), seed=101, amplitude=3)
    base = np.clip(240 + noise, 0, 255).astype(np.uint8)
    rgb = np.repeat(base[:, :, None], 3, axis=2)
    img = Image.fromarray(rgb, mode="RGB")
    draw = ImageDraw.Draw(img)
    draw.text((60, 60), "KAVACH NOISE BASELINE INVOICE", fill=(15, 15, 15))
    for i in range(8):
        draw.text((60, 140 + i * 70), f"Row {i + 1}: Standard consulting fee Rs. 5,000.00", fill=(20, 20, 20))
    img.save(path, format="PNG")
    return np.asarray(img, dtype=np.uint8)


def test_noise_clean_document_ignores_text_edges(tmp_path: Path) -> None:
    clean_path = tmp_path / "clean_noise.png"
    _make_clean_noisy_doc(clean_path)

    res = NoiseInconsistencyDetector().analyze(clean_path, [clean_path], {})[0]
    assert isinstance(res, DetectorResult)
    assert res.name == "noise_inconsistency"
    assert res.status == "passed"
    assert res.score < 0.3
    assert res.boxes == []


def test_noise_detects_inconsistent_patch(tmp_path: Path) -> None:
    tampered_path = tmp_path / "tampered_noise.png"
    arr = _make_clean_noisy_doc(tampered_path).copy()

    # Inject a 160x140 region with much stronger synthetic noise (simulating foreign paste)
    patch_noise = _deterministic_noise((140, 160), seed=999, amplitude=22)
    patch = np.clip(240 + patch_noise, 0, 255).astype(np.uint8)
    arr[620:760, 420:580] = np.repeat(patch[:, :, None], 3, axis=2)
    Image.fromarray(arr, mode="RGB").save(tampered_path, format="PNG")

    res = NoiseInconsistencyDetector().analyze(tampered_path, [tampered_path], {})[0]
    assert res.status == "suspicious"
    assert 0.35 <= res.score <= 0.80
    assert len(res.boxes) >= 1
    overlaps = any(
        b.x < 580 and b.x + b.w > 420 and b.y < 760 and b.y + b.h > 620
        for b in res.boxes
    )
    assert overlaps


def test_noise_blank_and_invalid(tmp_path: Path) -> None:
    blank = tmp_path / "blank.png"
    Image.new("RGB", (300, 300), color=(255, 255, 255)).save(blank)
    res_blank = NoiseInconsistencyDetector().analyze(blank, [blank], {})[0]
    assert res_blank.status == "inconclusive"

    res_missing = NoiseInconsistencyDetector().analyze(tmp_path / "missing.png", [], {})[0]
    assert res_missing.status == "error"
