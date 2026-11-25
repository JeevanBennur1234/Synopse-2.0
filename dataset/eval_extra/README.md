# Kavach Additional Independent Evaluation Set

This directory (`dataset/eval_extra/`) stores an **independent synthetic evaluation dataset** (4 clean + 4 tampered documents) kept strictly separate from the baseline evaluation dataset in `dataset/clean/`, `dataset/tampered/`, and `dataset/ground_truth/`.

All documents use fictional business names (`ORION LOGISTICS INDIA PVT LTD`, `MERIDIAN CLOUD SERVICES LLP`, `APEX SYNTHETIC BANK`) and carry `SAMPLE / TEST ONLY — SYNTHETIC DATA`.

## Regenerating

```bash
python scripts/generate_extra_samples.py
```

## Samples
- **Clean (`dataset/eval_extra/clean/`)**:
  - `extra_invoice_clean_igst.pdf` (inter-state 18% IGST invoice)
  - `extra_invoice_clean_receipt.png` (clean PNG invoice)
  - `extra_invoice_clean_photo.jpg` (clean JPEG invoice)
  - `extra_statement_clean_2p.pdf` (2-page bank statement with consistent balances)
- **Tampered (`dataset/eval_extra/tampered/`)**:
  - `extra_invoice_tampered_gstin_checksum.pdf` (valid pattern, altered GSTIN check digit)
  - `extra_invoice_tampered_igst_mix.pdf` (simultaneous CGST+SGST and IGST)
  - `extra_invoice_tampered_visual_ela_splice.jpg` (q=30 JPEG splice over Grand total)
  - `extra_invoice_tampered_metadata_gimp.png` (PNG `Software=GIMP 2.10.36` text chunk)
