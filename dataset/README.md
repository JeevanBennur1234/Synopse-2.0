# Kavach Synthetic Test Dataset

All files in `dataset/clean/` and `dataset/tampered/` are **SAMPLE / TEST ONLY** synthetic business documents created for hackathon testing across all Kavach modules. No real customer data or real company records are used.

## Regenerating Samples

```bash
python scripts/generate_samples.py
```

Dependencies: Python standard library, `Pillow`, and `numpy`.

## Dataset Inventory

### Clean Samples (`dataset/clean/`)
| File | Format | Purpose |
| --- | --- | --- |
| `invoice_clean_gst_01.pdf` | Native PDF | Clean GST invoice with valid GSTIN and consistent arithmetic (`10,000 + 900 + 900 = 11,800`) |
| `invoice_clean_01.png` | PNG | Clean raster GST invoice for OCR and image detectors |
| `invoice_clean_01.jpg` | JPEG | Clean JPEG GST invoice for ELA baseline and OCR |
| `invoice_scanned_clean_01.pdf` | Scanned PDF | Image-only PDF with scanner tilt/grain to exercise Tesseract OCR |
| `bank_statement_clean_01.pdf` | Native PDF (2 pages) | Clean multi-page bank statement with consistent running balances |

### Tampered Samples (`dataset/tampered/`)
| File | Target Detector | Expected Anomaly |
| --- | --- | --- |
| `invoice_tampered_grand_total.pdf` | Consistency | Grand total `19,800.00` does not match `10,000 + 900 + 900` |
| `invoice_tampered_invalid_gstin.pdf` | Consistency | Invalid GSTIN `99INVALID1234Z0` |
| `invoice_tampered_tax_mismatch.pdf` | Consistency | Asymmetric CGST (`1,400.00`) vs SGST (`900.00`) against 9%+9% declaration |
| `bank_statement_tampered_balance.pdf` | Consistency | Multi-page statement with `+10,000.00` running balance break on page 2 |
| `invoice_scanned_tampered_total.pdf` | OCR + Consistency | Scanned invoice with altered Grand total (`18,800.00`) |
| `invoice_tampered_visual_ela.jpg` | Visual (`ela`) | Spliced `q=35` JPEG patch over Grand total on `q=95` invoice |
| `invoice_tampered_visual_copy_move.png` | Visual (`copy_move`) | Cloned authorization stamp duplicated onto center-left area |
| `invoice_tampered_visual_noise.png` | Visual (`noise_inconsistency`) | Elevated noise patch (`sigma=16`) over Grand total on `sigma=4.5` scan |
| `invoice_tampered_metadata_edited.jpg` | Image Metadata | EXIF `Software=Adobe Photoshop CC 2024` and `>24h` timestamp gap |

## Ground Truth (`dataset/ground_truth/`)

Each sample has an individual JSON annotation file plus a combined `dataset/ground_truth/manifest.json` containing:
- `filename`, `relative_path`, `document_type`, `label`, `format`
- `expected_anomalies`
- `affected_page` (0-based)
- `known_affected_regions` (`page`, `x`, `y`, `w`, `h` in rendered pixel coordinates matching `backend/app/schemas.py`)
