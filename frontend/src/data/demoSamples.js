// Isolated DEMO PREVIEW fixtures for offline UI walkthroughs.
// Strictly separated from live backend API responses and always badged as DEMO ONLY.

function makeSvgPageDataUrl({ title, subtitle, lines, highlightLabel, highlightY }) {
  const rows = lines
    .map(
      (line, idx) =>
        `<text x="72" y="${260 + idx * 44}" font-family="monospace" font-size="22" fill="#1e293b">${line}</text>`
    )
    .join("");

  const highlightMarkup = highlightLabel
    ? `<rect x="655" y="${highlightY}" width="465" height="58" rx="4" fill="#fef2f2" stroke="#cbd5e1" stroke-width="2"/>
       <text x="672" y="${highlightY + 36}" font-family="monospace" font-size="24" font-weight="bold" fill="#0f172a">${highlightLabel}</text>`
    : "";

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1190" height="1684" viewBox="0 0 1190 1684">
    <rect width="1190" height="1684" fill="#ffffff"/>
    <rect x="48" y="42" width="1094" height="68" fill="#0f172a"/>
    <text x="76" y="84" font-family="sans-serif" font-size="22" font-weight="bold" fill="#f8fafc">DEMO PREVIEW — SAMPLE / TEST ONLY</text>
    <text x="72" y="165" font-family="sans-serif" font-size="34" font-weight="bold" fill="#0f172a">${title}</text>
    <text x="72" y="205" font-family="sans-serif" font-size="20" fill="#475569">${subtitle}</text>
    <line x1="60" y1="225" x2="1130" y2="225" stroke="#cbd5e1" stroke-width="2"/>
    ${rows}
    ${highlightMarkup}
    <text x="72" y="1610" font-family="sans-serif" font-size="18" fill="#64748b">Simulated Demo Preview — Not a Live Detector Result</text>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export const DEMO_SCENARIOS = {
  inconclusive_foundation: {
    id: "inconclusive_foundation",
    label: "Demo: Current Backend (Detectors Unregistered)",
    filename: "invoice_clean_gst_01.pdf",
    result: {
      job_id: "demo-inconclusive-001",
      status: "completed",
      risk_score: null,
      risk_level: "inconclusive",
      coverage: 0,
      findings: [],
      engine_runs: [
        { engine: "visual", status: "unavailable", finding_count: 0 },
        { engine: "file_forensics", status: "unavailable", finding_count: 0 },
        { engine: "consistency", status: "unavailable", finding_count: 0 },
      ],
      fields: {
        invoice_number: ["INV-2026-001"],
        gstin: ["29KAVCH1234F1Z4", "27SYNTH5678G1Z6"],
        ifsc: ["SYNB0001234"],
        dates: ["25/11/2026"],
        subtotal: ["10,000.00"],
        cgst: ["900.00"],
        sgst: ["900.00"],
        total: ["11,800.00"],
      },
      field_locations: {
        total: [{ value: "11,800.00", page: 0, x: 672, y: 952, w: 145, h: 32, confidence: null }],
      },
      warnings: [
        "visual: detector not registered",
        "file_forensics: detector not registered",
        "consistency: detector not registered",
        "Insufficient conclusive evidence for overall risk.",
      ],
      pages: [
        {
          page: 0,
          width: 1190,
          height: 1684,
          method: "native_pdf",
          text: "SAMPLE / TEST ONLY — INV-2026-001",
          words: [],
          preview_url: makeSvgPageDataUrl({
            title: "KAVACH TEST SUPPLIES PVT LTD",
            subtitle: "Invoice no: INV-2026-001 | GSTIN: 29KAVCH1234F1Z4",
            lines: [
              "Date: 25/11/2026",
              "Subtotal: INR 10,000.00",
              "CGST: INR 900.00",
              "SGST: INR 900.00",
              "IGST: INR 0.00",
            ],
            highlightLabel: "Grand total: INR 11,800.00",
            highlightY: 938,
          }),
        },
      ],
    },
  },
  tampered_invoice: {
    id: "tampered_invoice",
    label: "Demo: Tampered GST Invoice (High Risk)",
    filename: "invoice_tampered_visual_ela.jpg",
    result: {
      job_id: "demo-tampered-002",
      status: "completed",
      risk_score: 82.5,
      risk_level: "high",
      coverage: 1.0,
      engine_runs: [
        { engine: "visual", status: "completed", finding_count: 2 },
        { engine: "file_forensics", status: "completed", finding_count: 1 },
        { engine: "consistency", status: "completed", finding_count: 1 },
      ],
      findings: [
        {
          name: "ela",
          score: 0.84,
          confidence: 0.91,
          status: "suspicious",
          evidence:
            "Localized JPEG compression mismatch (z-score 6.4) detected around the Grand total field compared to surrounding baseline.",
          boxes: [{ page: 0, x: 655, y: 938, w: 465, h: 58 }],
        },
        {
          name: "image_metadata",
          score: 0.0,
          confidence: 0.2,
          status: "inconclusive",
          evidence: "EXIF software metadata was stripped; missing metadata is inconclusive.",
          boxes: [],
        },
        {
          name: "file_forensics",
          score: 0.12,
          confidence: 0.8,
          status: "passed",
          evidence: "No anomalous PDF trailer or embedded script structures found.",
          boxes: [],
        },
        {
          name: "consistency",
          score: 0.92,
          confidence: 0.98,
          status: "suspicious",
          evidence:
            "Subtotal (10,000.00) + CGST (900.00) + SGST (900.00) = 11,800.00, which conflicts with extracted Grand total (31,800.00).",
          boxes: [{ page: 0, x: 655, y: 938, w: 465, h: 58 }],
        },
      ],
      fields: {
        invoice_number: ["INV-2026-201"],
        gstin: ["29KAVCH1234F1Z4"],
        dates: ["25/11/2026"],
        subtotal: ["10,000.00"],
        cgst: ["900.00"],
        sgst: ["900.00"],
        total: ["31,800.00"],
      },
      field_locations: {
        total: [{ value: "31,800.00", page: 0, x: 672, y: 952, w: 145, h: 32, confidence: 0.95 }],
      },
      warnings: ["Demo preview fixture: simulated detector outputs for UI verification."],
      pages: [
        {
          page: 0,
          width: 1190,
          height: 1684,
          method: "ocr",
          text: "SAMPLE / TEST ONLY — INV-2026-201",
          words: [],
          preview_url: makeSvgPageDataUrl({
            title: "KAVACH TEST SUPPLIES PVT LTD",
            subtitle: "Invoice no: INV-2026-201 | GSTIN: 29KAVCH1234F1Z4",
            lines: [
              "Date: 25/11/2026",
              "Subtotal: INR 10,000.00",
              "CGST: INR 900.00",
              "SGST: INR 900.00",
              "Expected Total: INR 11,800.00",
            ],
            highlightLabel: "Grand total: INR 31,800.00",
            highlightY: 938,
          }),
        },
      ],
    },
  },
  multipage_bank: {
    id: "multipage_bank",
    label: "Demo: 2-Page Bank Statement (Page 2 Anomaly)",
    filename: "bank_statement_tampered_balance.pdf",
    result: {
      job_id: "demo-bank-003",
      status: "completed",
      risk_score: 64.0,
      risk_level: "medium",
      coverage: 0.7,
      engine_runs: [
        { engine: "visual", status: "inconclusive", finding_count: 1 },
        { engine: "file_forensics", status: "completed", finding_count: 1 },
        { engine: "consistency", status: "completed", finding_count: 1 },
      ],
      findings: [
        {
          name: "consistency",
          score: 0.85,
          confidence: 0.94,
          status: "suspicious",
          evidence:
            "Page 2 row 1 (14/11/2026): prior balance 200,000.00 - debit 12,000.00 should equal 188,000.00, but statement reports 198,000.00.",
          boxes: [{ page: 1, x: 655, y: 270, w: 465, h: 58 }],
        },
        {
          name: "file_forensics",
          score: 0.15,
          confidence: 0.75,
          status: "passed",
          evidence: "Single PDF revision detected; standard Type1 fonts only.",
          boxes: [],
        },
      ],
      fields: {
        ifsc: ["SYNB0001234"],
        opening_balance: ["150,000.00"],
        closing_balance: ["194,500.00"],
      },
      field_locations: {},
      warnings: ["Demo preview fixture: visual engine marked inconclusive (30% weight excluded)."],
      pages: [
        {
          page: 0,
          width: 1190,
          height: 1684,
          method: "native_pdf",
          text: "Bank statement page 1",
          words: [],
          preview_url: makeSvgPageDataUrl({
            title: "SYNTHETIC NATIONAL BANK (Page 1/2)",
            subtitle: "IFSC: SYNB0001234 | Opening balance: INR 150,000.00",
            lines: [
              "02/11/2026 | Debit 12,500.00 | Bal: 137,500.00",
              "05/11/2026 | Credit 45,000.00 | Bal: 182,500.00",
              "08/11/2026 | Debit 4,500.00 | Bal: 178,000.00",
              "11/11/2026 | Credit 22,000.00 | Bal: 200,000.00",
            ],
            highlightLabel: null,
            highlightY: 0,
          }),
        },
        {
          page: 1,
          width: 1190,
          height: 1684,
          method: "native_pdf",
          text: "Bank statement page 2",
          words: [],
          preview_url: makeSvgPageDataUrl({
            title: "SYNTHETIC NATIONAL BANK (Page 2/2)",
            subtitle: "Carried forward from Page 1: INR 200,000.00",
            lines: [
              "14/11/2026 | Debit 12,000.00 | Expected: 188,000.00",
              "17/11/2026 | Credit 6,500.00 | Bal: 204,500.00",
              "20/11/2026 | Debit 10,000.00 | Closing: 194,500.00",
            ],
            highlightLabel: "Reported Bal: INR 198,000.00",
            highlightY: 270,
          }),
        },
      ],
    },
  },
};
