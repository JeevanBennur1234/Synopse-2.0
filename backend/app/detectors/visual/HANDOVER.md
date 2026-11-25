# Visual & Image Metadata Forensics — Technical Handover (Phase 2)

## 1. Detector Names
Running `analyze(source, pages, fields)` returns 5 `DetectorResult` items in order:
1. `ela` — Luminance-channel 8×8-block Error Level Analysis (`ela.py`)
2. `copy_move` — ORB + shift-clustering + NCC region duplication detector with header/footer branding context (`copy_move.py`)
3. `noise_inconsistency` — Local background noise MAD outlier detector (`noise.py`)
4. `image_metadata` — EXIF / PNG text chunk software & timestamp inspector (`image_metadata/analyzer.py`)
5. `typography` — Line-scoped visual typography + native PDF font-span consistency detector (`typography.py`)

Additional P1 support modules (non-scoring, read-only):
- `evidence_fusion.py`: `correlate_evidence(results)` groups overlapping/contained same-page bounding boxes across detectors without mutating scores or confidences.
- `heatmap.py`: `render_page_overlay(...)` and `render_multipage_overlays(...)` render individual, combined, and side-by-side overlays in original page pixel coordinates.

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
- `source`: `pathlib.Path` to original uploaded file (never modified).
- `pages`: `list[pathlib.Path]` of rendered page images in zero-based page order.
- `fields`: `dict[str, Any]` containing extracted field candidate lists.
- Sub-detector exceptions are isolated and returned as `DetectorResult(status="error", ...)`.

## 3. Required Python Dependencies (for `backend/requirements.txt`)
- `opencv-python` (tested on `5.1.0.95` / `5.0.0`)
- `pillow` (`12.2.0`)
- `numpy` (`2.4.6`)
- `PyMuPDF` (optional for native PDF font-span inspection in `typography.py`; falls back gracefully to visual line analysis if unavailable)
- `pydantic>=2`

## 4. Key Algorithm Thresholds
- **ELA (`ela.py`)**: Luminance (`Y`) recompression at `quality=90`; 8×8 block aggregation + 3×3 block smoothing; active-block (`local_blk_grad > 4.0`) median ratio `1.35 * med_ratio`; `z_thresh = 3.8`, `min_abs_excess = 0.75`, `min_abs_blk_ela = max(med_ela + 1.8, 2.35)`, `b_w >= 2, b_h >= 2`, `min_blk_area = 4`.
- **Copy-Move (`copy_move.py`)**: `MAX_PROCESS_DIM = 1600`, `ORB nfeatures = 2500`, `MAX_HAMMING_DIST = 28`, `MIN_CLUSTER_MATCHES = 8`, `SHIFT_BIN_SIZE = 16`, `SPATIAL_LINK_RADIUS = 28.0`, `MIN_PATCH_CORR = 0.88`, self-overlap rejection `> 15%`. Margin branding (`y < 18%` or `y > 82%`) or 3+ repetitive layout copies return `inconclusive` (`score=0.22`, `confidence=0.40`).
- **Noise (`noise.py`)**: `BLOCK_SIZE = 48`, `EDGE_GRAD_THRESH = 60.0` (on 5×5 Gaussian-smoothed image), `MIN_NON_EDGE_RATIO = 0.35`, `Z_THRESH = 4.5`, `MIN_ABS_NOISE_DIFF = 1.8`.
- **Typography (`typography.py`)**: Line height `10..65px`, word `w >= 14, h >= 8..55`; flags only when `>= 2` corroborating cues occur within the same line (`local_bg_diff >= 18`, `ΔRGB >= 55`, `baseline_shift >= max(5, 0.32*h)` or `height_mismatch >= 45%`, `stroke_diff >= 65%`), or native PDF span size diff `>= 1.8pt` / baseline shift `>= 3.0pt` within contiguous spans (`max_gap <= 35pt`).

## 5. Measured Evaluation (28 Synthetic Documents + 30 Unit Tests)
- **Unit & robustness tests**: `python -m pytest backend/tests/test_visual -v` -> **30 passed in 25.20s**.
- **28-sample dataset summary**:
  - `ela`: `TP=2, FP=0, FN=0, TN=3, NA=23 | P=1.00, R=1.00, F1=1.00, FPR=0.000`
  - `copy_move`: `TP=1, FP=0, FN=0, TN=27 | P=1.00, R=1.00, F1=1.00, FPR=0.000, avgIoU=0.80`
  - `noise_inconsistency`: `TP=1, FP=2 (on tampered JPEG splices; 0 on clean), FN=0, TN=25 | P=0.33, R=1.00, F1=0.50, FPR=0.074, avgIoU=0.73`
  - `image_metadata`: `TP=2, FP=0, FN=0, NA=18, INC=8 | P=1.00, R=1.00, F1=1.00, FPR=0.000`
  - `typography`: `TP=0, FP=0, FN=0, TN=28 | FPR=0.000` (validated on synthetic tampered-amount test)
- **Measured latency by format (all 5 detectors)**: PDF avg `1.111s`, PNG avg `1.022s`, JPG avg `1.329s`.
