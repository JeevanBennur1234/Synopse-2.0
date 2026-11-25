# Kavach Demo & Team Verification Runbook

## 1. Starting the Application Locally

### Backend (FastAPI on port 8000)
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```
Swagger UI: http://localhost:8000/docs

### Frontend (React + Vite on port 5173)
```bash
cd frontend
npm install
npm run dev
```
Open: http://localhost:5173

The Vite dev server proxies `/api/*` directly to `http://localhost:8000/*` (configured in `frontend/vite.config.js`), avoiding CORS blocks during local development. To point directly to a deployed API with CORS enabled, set `VITE_API_BASE_URL` in `frontend/.env`.

---

## 2. 3-Minute Live Demo Sequence

1. **0:00–0:25 — System Readiness & Clean Baseline**
   - Confirm the top-right status pill reads **Backend Connected**.
   - Upload `dataset/clean/invoice_clean_gst_01.pdf` and click **Analyze Document**.
   - Highlight the extracted GSTIN, invoice number, subtotal (`10,000.00`), CGST (`900.00`), SGST (`900.00`), and grand total (`11,800.00`).
   - Note honesty guardrails: if an engine is unregistered or lacks `>= 60%` weighted coverage, Kavach reports **Inconclusive** rather than fabricating a clean score.

2. **0:25–1:00 — Business Consistency Anomaly (Invalid GSTIN / Incorrect Total)**
   - Upload `dataset/tampered/invoice_tampered_grand_total.pdf` (or `dataset/tampered/invoice_tampered_invalid_gstin.pdf`).
   - Point out the flagged **Business Consistency** finding explaining the exact arithmetic discrepancy (`10,000 + 900 + 900 = 11,800` vs `19,800`) or invalid GSTIN (`99INVALID1234Z0`), plus the extracted fields panel.

3. **1:00–1:40 — Visual Forensics Tampering**
   - Upload `dataset/tampered/invoice_tampered_visual_ela.jpg` (or `dataset/tampered/invoice_tampered_visual_copy_move.png`).
   - Click the red bounding box overlay in the **Interactive Document Viewer** (or click the region chip on the finding card) to link the evidence directly to the affected region. Demonstrate zoom (`125%`) and overlay toggle (`Regions`).

4. **1:40–2:20 — Multi-Page Document Screening**
   - Upload `dataset/tampered/bank_statement_tampered_balance.pdf` (2-page synthetic bank statement).
   - Use **Next page** in the viewer to jump to Page 2/2 and show the flagged `+10,000.00` running balance break.

5. **2:20–3:00 — Forensic Report & Honest Limitations**
   - Click **Export Report** in the header to open the print-ready report preview showing Document ID, risk score, analysis coverage, findings, cropped suspicious region previews, extracted fields, and **Download JSON**.
   - Explain limitations honestly:
     - Risk scores are screening indicators, not legal proof of forgery.
     - Missing checks or stripped metadata (e.g., WhatsApp/scanner re-encoding) yield `inconclusive`, never `clean`.
     - If the backend is unavailable offline, use **Load Demo Preview...** (explicitly badged **Demo Preview Only — Not Real Analysis**).
