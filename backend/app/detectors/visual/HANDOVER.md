# Visual & Image Metadata Forensics — Technical Handover

## 1. Detector Names
Running `analyze(source, pages, fields)` returns 4 `DetectorResult` items in order:
1. `ela` — Error Level Analysis (JPEG compression consistency)
2. `copy_move` — ORB keypoint + shift-clustering + NCC region duplication detector
3. `noise_inconsistency` — Local background noise MAD outlier detector
4. `image_metadata` — EXIF / PNG text chunk software & timestamp inspector

## 2. Integration Usage
```python
from pathlib import Path
from app.detectors.visual import analyze

results = analyze(
    source=Path("/path/to/original_upload.jpg"),
    pages=[Path("/path/to/page_0.png")],
    fields={"invoice_number": ["INV-001"]},
)
```
- `source`: `pathlib.Path` to the original uploaded file (never modified).
- `pages`: `list[pathlib.Path]` of rendered page images in zero-based page order.
- `fields`: `dict[str, Any]` (accepts extracted field candidate lists).
- Exceptions in any sub-detector are caught and returned as `DetectorResult(status="error", ...)` without crashing the remaining detectors.

## 3. Required Python Dependencies (for `backend/requirements.txt`)
Verified in this environment:
- `opencv-python==5.0.0.93` (`cv2` 5.0.0)
- `pillow==12.2.0`
- `numpy==2.4.6`
- `pydantic>=2` (already in `requirements.txt`)

## 4. Algorithm Thresholds
- **ELA (`ela.py`)**: `DEFAULT_RECOMPRESS_QUALITY = 90`, `z_thresh = 4.5`, `min_abs_ela = max(med_ela + 2.5, 4.0)`, `min_area = max(250, 0.05% of page)`, `max_area = 45% of page`, `MIN_IMAGE_DIM = 64`.
- **Copy-Move (`copy_move.py`)**: `MAX_PROCESS_DIM = 1600`, `ORB nfeatures = 2500`, `MAX_HAMMING_DIST = 28`, `MIN_CLUSTER_MATCHES = 8`, `SHIFT_BIN_SIZE = 16`, `SPATIAL_LINK_RADIUS = 28.0`, `MIN_PATCH_CORR = 0.88`, self-overlap rejection `> 15%`.
- **Noise Inconsistency (`noise.py`)**: `BLOCK_SIZE = 48`, `EDGE_GRAD_THRESH = 60.0` (on 5x5 Gaussian-smoothed image), `MIN_NON_EDGE_RATIO = 0.35`, `Z_THRESH = 4.5`, `MIN_ABS_NOISE_DIFF = 1.8`.
- **Image Metadata (`analyzer.py`)**: `EDITING_SOFTWARE_KEYWORDS` (`photoshop`, `adobe`, `gimp`, `canva`, `snapseed`, `picsart`, `lightroom`, `affinity`, `paint.net`, `pixlr`, `fotor`, `inkscape`, `coreldraw`, `iloveimg`, `photopea`, `facetune`), timestamp gap threshold `> 24h` or `DateTime < DateTimeOriginal - 5m`.

## 5. Score & Confidence Interpretation
- All `score` and `confidence` values are bounded in `[0.0, 1.0]`.
- `passed`: `score` in `0.00 - 0.18` (no localized anomaly detected).
- `suspicious`: `score` capped at `0.85` (`ela`, `copy_move`) or `0.80` (`noise_inconsistency`, `image_metadata`); risk indicators are never reported as `1.0` proof of forgery.
- `inconclusive`: `score = 0.0`, low confidence (`0.10 - 0.25`) for blank/tiny images or stripped EXIF metadata.
- `not_applicable`: `score = 0.0`, `confidence = 0.0` (e.g., `ela` on PNG/PDF; `image_metadata` on PDF, which is owned by `file_forensics`).

## 6. Supported Formats & Known Limitations
- **Formats**: Original `source` in `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`, `.webp`, `.bmp`, or `.pdf` (with rendered `pages`).
- **Limitations**:
  - `ela` applies only to original `.jpg`/`.jpeg` uploads; PNGs and PDF-rendered pages lack original JPEG quantization history.
  - `copy_move` can flag genuinely repeated visual elements such as identical company logos or stamps appearing twice on the same page.
  - `image_metadata` returns `inconclusive` when messaging apps or scanners strip EXIF/PNG metadata; missing metadata does not imply forgery.
  - Detection accuracy on real-world forged documents is not claimed without evaluating on Member 4's shared synthetic/consented dataset.

## 7. Measured Test Results & Latency
- **Test suite**: `python -m pytest backend/tests/test_visual -v` -> **23 passed in 9.79s**.
- **Measured single-page JPEG latency (800x1000)**: `0.838s` total across all 4 detectors (`ela`: `0.0129`, `copy_move`: `0.05`, `noise_inconsistency`: `0.0076`, `image_metadata`: `0.0` inconclusive when EXIF stripped).
