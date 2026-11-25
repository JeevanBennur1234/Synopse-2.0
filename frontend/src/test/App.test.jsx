import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";

function mockJsonResponse(body, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
}

describe("Kavach Frontend End-to-End Workflows", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows backend unavailable state when /health fails", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Network down"))));
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Backend Offline/i)).toBeInTheDocument();
    });
    expect(screen.getByText(/Backend server unreachable/i)).toBeInTheDocument();
  });

  it("rejects invalid file extensions in the upload panel", async () => {
    vi.stubGlobal("fetch", vi.fn(() => mockJsonResponse({ status: "ok" })));
    render(<App />);

    await waitFor(() => {
      expect(screen.getByText(/Backend Connected/i)).toBeInTheDocument();
    });

    const input = document.querySelector('input[type="file"]');
    const badFile = new File(["not-allowed"], "script.exe", {
      type: "application/x-msdownload",
    });
    fireEvent.change(input, { target: { files: [badFile] } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/Unsupported file type/i);
  });

  it("handles PDF upload, queued/running polling, and completed null-risk result", async () => {
    let pollCount = 0;
    const fetchMock = vi.fn((url) => {
      if (url.endsWith("/health")) {
        return mockJsonResponse({ status: "ok" });
      }
      if (url.endsWith("/analyze")) {
        return mockJsonResponse({ job_id: "job-null-1", status: "queued" }, 202);
      }
      if (url.includes("/result/job-null-1")) {
        pollCount += 1;
        if (pollCount === 1) {
          return mockJsonResponse({
            job_id: "job-null-1",
            status: "running",
            risk_score: null,
            risk_level: "inconclusive",
            coverage: 0,
            findings: [],
            pages: [],
            fields: {},
            warnings: [],
            engine_runs: [],
          });
        }
        return mockJsonResponse({
          job_id: "job-null-1",
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
          fields: { total: ["11,800.00"] },
          field_locations: {},
          warnings: [
            "visual: detector not registered",
            "Insufficient conclusive evidence for overall risk.",
          ],
          pages: [
            {
              page: 0,
              width: 1190,
              height: 1684,
              text: "Grand total: 11,800.00",
              words: [],
              method: "native_pdf",
              preview_url: "/result/job-null-1/pages/0",
            },
          ],
        });
      }
      return mockJsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Backend Connected/i)).toBeInTheDocument();
    });

    const input = document.querySelector('input[type="file"]');
    const pdfFile = new File(["%PDF-1.4"], "invoice_clean.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [pdfFile] } });

    expect(screen.getByText("invoice_clean.pdf")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Analyze Document/i }));

    await waitFor(
      () => {
        expect(screen.getByText(/Overall Risk Assessment/i)).toBeInTheDocument();
      },
      { timeout: 3000 }
    );

    expect(screen.getAllByText(/Inconclusive/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/^0%$/)).toBeInTheDocument();
    expect(screen.getByText(/visual: detector not registered/i)).toBeInTheDocument();
  });

  it("handles image upload, actual findings, bounding boxes, and printable report", async () => {
    const fetchMock = vi.fn((url) => {
      if (url.endsWith("/health")) {
        return mockJsonResponse({ status: "ok" });
      }
      if (url.endsWith("/analyze")) {
        return mockJsonResponse({ job_id: "job-img-2", status: "queued" }, 202);
      }
      if (url.includes("/result/job-img-2")) {
        return mockJsonResponse({
          job_id: "job-img-2",
          status: "completed",
          risk_score: 84.5,
          risk_level: "high",
          coverage: 1.0,
          engine_runs: [
            { engine: "visual", status: "completed", finding_count: 1 },
            { engine: "file_forensics", status: "completed", finding_count: 0 },
            { engine: "consistency", status: "completed", finding_count: 1 },
          ],
          findings: [
            {
              name: "ela",
              score: 0.85,
              confidence: 0.92,
              status: "suspicious",
              evidence: "Compression splice detected over Grand total.",
              boxes: [{ page: 0, x: 700, y: 990, w: 450, h: 70 }],
            },
            {
              name: "consistency",
              score: 0.9,
              confidence: 0.95,
              status: "suspicious",
              evidence: "Total mismatch detected.",
              boxes: [],
            },
          ],
          fields: { invoice_number: ["INV-2026-201"], total: ["31,800.00"] },
          field_locations: {},
          warnings: [],
          pages: [
            {
              page: 0,
              width: 1240,
              height: 1754,
              text: "Grand total: 31,800.00",
              words: [],
              method: "ocr",
              preview_url: "/result/job-img-2/pages/0",
            },
          ],
        });
      }
      return mockJsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Backend Connected/i)).toBeInTheDocument();
    });

    const input = document.querySelector('input[type="file"]');
    const imgFile = new File(["img"], "tampered.jpg", { type: "image/jpeg" });
    fireEvent.change(input, { target: { files: [imgFile] } });
    fireEvent.click(screen.getByRole("button", { name: /Analyze Document/i }));

    await waitFor(() => {
      expect(screen.getByText("84.5")).toBeInTheDocument();
    });

    expect(screen.getByText("High Risk")).toBeInTheDocument();
    expect(screen.getByText(/Compression splice detected over Grand total/i)).toBeInTheDocument();
    expect(screen.getByText(/Regions \(1\)/i)).toBeInTheDocument();

    // Open printable report modal
    fireEvent.click(screen.getByRole("button", { name: /Export Report/i }));
    expect(screen.getByText(/Kavach Forensic Analysis Report Preview/i)).toBeInTheDocument();
    expect(screen.getByText(/Suspicious Region Previews/i)).toBeInTheDocument();
  });

  it("handles failed analysis state cleanly", async () => {
    const fetchMock = vi.fn((url) => {
      if (url.endsWith("/health")) {
        return mockJsonResponse({ status: "ok" });
      }
      if (url.endsWith("/analyze")) {
        return mockJsonResponse({ job_id: "job-fail-3", status: "queued" }, 202);
      }
      if (url.includes("/result/job-fail-3")) {
        return mockJsonResponse({
          job_id: "job-fail-3",
          status: "failed",
          risk_score: null,
          risk_level: "inconclusive",
          coverage: 0,
          findings: [],
          pages: [],
          fields: {},
          warnings: ["Document processing failed."],
          engine_runs: [],
        });
      }
      return mockJsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Backend Connected/i)).toBeInTheDocument();
    });

    const input = document.querySelector('input[type="file"]');
    const pdfFile = new File(["%PDF-1.4"], "corrupt.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [pdfFile] } });
    fireEvent.click(screen.getByRole("button", { name: /Analyze Document/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Document processing failed/i
    );
  });

  it("supports multi-page navigation in isolated demo preview mode", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline"))));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Backend Offline/i)).toBeInTheDocument();
    });

    const demoSelect = screen.getByLabelText(/Load isolated demo preview/i);
    fireEvent.change(demoSelect, { target: { value: "multipage_bank" } });

    expect(screen.getByText(/Demo Preview Mode:/i)).toBeInTheDocument();
    expect(screen.getByText(/Page 1 of 2/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Next page/i }));
    expect(screen.getByText(/Page 2 of 2/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Previous page/i }));
    expect(screen.getByText(/Page 1 of 2/i)).toBeInTheDocument();
  });

  it("cleans up polling timers on component unmount", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((url) => {
      if (url.endsWith("/health")) {
        return mockJsonResponse({ status: "ok" });
      }
      if (url.endsWith("/analyze")) {
        return mockJsonResponse({ job_id: "job-unmount", status: "queued" }, 202);
      }
      return mockJsonResponse({
        job_id: "job-unmount",
        status: "running",
        risk_score: null,
        risk_level: "inconclusive",
        coverage: 0,
        findings: [],
        pages: [],
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = render(<App />);
    await act(async () => {
      await Promise.resolve();
    });

    const input = document.querySelector('input[type="file"]');
    const pdfFile = new File(["%PDF-1.4"], "sample.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [pdfFile] } });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Analyze Document/i }));
      await Promise.resolve();
    });

    const callsBeforeUnmount = fetchMock.mock.calls.length;
    unmount();

    await act(async () => {
      vi.advanceTimersByTime(5000);
      await Promise.resolve();
    });

    expect(fetchMock.mock.calls.length).toBe(callsBeforeUnmount);
  });

  it("shows Manual review required warning on low aggregate risk with suspicious finding and exports real report JSON", async () => {
    const realPhase13Payload = {
      job_id: "job-ela-low-risk",
      status: "completed",
      review_required: true,
      check_status_counts: { passed: 3, suspicious: 2, inconclusive: 9, not_applicable: 1, error: 0 },
      risk_score: 26.46,
      risk_level: "low",
      coverage: 1.0,
      engine_runs: [
        { engine: "visual", status: "completed", finding_count: 4 },
        { engine: "file_forensics", status: "not_applicable", finding_count: 1 },
        { engine: "consistency", status: "completed", finding_count: 10 },
      ],
      findings: [
        {
          name: "ela",
          score: 0.7056,
          confidence: 0.75,
          status: "suspicious",
          evidence: "Page 0: detected 1 localized JPEG error-level outlier(s).",
          boxes: [{ page: 0, x: 136, y: 924, w: 135, h: 86 }],
        },
        {
          name: "noise_inconsistency",
          score: 0.5961,
          confidence: 0.6859,
          status: "suspicious",
          evidence: "Page 0: detected 1 region(s) with anomalous background noise.",
          boxes: [{ page: 0, x: 720, y: 1008, w: 288, h: 48 }],
        },
        {
          name: "calendar_date_validity",
          score: 0.0,
          confidence: 0.9,
          status: "passed",
          evidence: "Validated 2 calendar date(s).",
          boxes: [{ page: 0, x: 840, y: 206, w: 98, h: 15 }],
        },
      ],
      fields: { gstin: ["29KAVCH1234F1Z4"], total: ["31,800.00"] },
      field_locations: {},
      warnings: [],
      registry_checks: [
        { gstin: "29KAVCH1234F1Z4", status: "synthetic_match", message: "Matched local synthetic registry entry." },
      ],
      explanation: {
        summary: "Overall heuristic risk is low (26.46/100). 2 suspicious finding(s); engine evidence coverage 100%.",
        reasons: [
          { detector: "ela", evidence: "Page 0: detected 1 localized JPEG error-level outlier(s).", confidence: 0.75, pages: [0] },
        ],
        limitations: ["Risk is a heuristic, not a probability of fraud or proof of authenticity."],
        recommendation: "Review highlighted evidence and verify against original records.",
        method: "deterministic",
      },
      pages: [
        {
          page: 0,
          width: 1240,
          height: 1754,
          text: "SAMPLE / TEST ONLY",
          words: [],
          method: "ocr",
          preview_url: "/result/job-ela-low-risk/pages/0",
        },
      ],
    };

    const fetchMock = vi.fn((url) => {
      if (url.endsWith("/health")) return mockJsonResponse({ status: "ok" });
      if (url.endsWith("/analyze")) return mockJsonResponse({ job_id: "job-ela-low-risk", status: "queued" }, 202);
      if (url.includes("/result/job-ela-low-risk")) return mockJsonResponse(realPhase13Payload);
      return mockJsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    let capturedBlob = null;
    const origCreateObjectURL = URL.createObjectURL;
    const origRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn((blob) => {
      capturedBlob = blob;
      return "blob:mock-report";
    });
    URL.revokeObjectURL = vi.fn();

    render(<App />);
    await waitFor(() => expect(screen.getByText(/Backend Connected/i)).toBeInTheDocument());

    const input = document.querySelector('input[type="file"]');
    fireEvent.change(input, {
      target: { files: [new File(["jpg"], "invoice_tampered_visual_ela.jpg", { type: "image/jpeg" })] },
    });
    fireEvent.click(screen.getByRole("button", { name: /Analyze Document/i }));

    await waitFor(() => expect(screen.getByText("26.5")).toBeInTheDocument());
    expect(screen.getByText(/Manual review required\. Inspect individual findings and limitations regardless of aggregate risk\./i)).toBeInTheDocument();
    expect(screen.getByText("Low risk, 2 signals found, manual review suggested")).toBeInTheDocument();
    expect(screen.getByText(/Mock GST Registry \(Synthetic Only\)/i)).toBeInTheDocument();

    // Verify overlay alignment math across zoom changes when image layout size updates
    const img = screen.getByAltText("Document page 1");
    Object.defineProperty(img, "clientWidth", { value: 620, configurable: true });
    Object.defineProperty(img, "clientHeight", { value: 877, configurable: true });
    fireEvent.load(img);

    let overlays = screen.getAllByTestId("overlay-box");
    expect(overlays[0].style.left).toBe("68px");
    expect(overlays[0].style.top).toBe("462px");

    Object.defineProperty(img, "clientWidth", { value: 930, configurable: true });
    Object.defineProperty(img, "clientHeight", { value: 1315.5, configurable: true });
    fireEvent.click(screen.getByRole("button", { name: /Zoom in/i }));
    await waitFor(() => {
      overlays = screen.getAllByTestId("overlay-box");
      expect(overlays[0].style.left).toBe("102px");
      expect(overlays[0].style.top).toBe("693px");
    });

    // Open PrintableReport and verify suspicious-only previews + JSON export
    fireEvent.click(screen.getByRole("button", { name: /Export Report/i }));
    expect(screen.getByText(/Suspicious Region Previews/i)).toBeInTheDocument();
    expect(screen.queryByText(/Calendar Date Validity • Page 1/i)).not.toBeInTheDocument();

    const anchorClickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    fireEvent.click(screen.getByRole("button", { name: /Download JSON/i }));
    expect(anchorClickSpy).toHaveBeenCalled();
    expect(capturedBlob).not.toBeNull();
    const blobText = await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.readAsText(capturedBlob);
    });
    const exportedJson = JSON.parse(blobText);
    expect(exportedJson.job_id).toBe("job-ela-low-risk");
    expect(exportedJson.review_required).toBe(true);
    expect(exportedJson.risk_score).toBe(26.46);
    expect(exportedJson.risk_summary).toBe("Low risk, 2 signals found, manual review suggested");
    expect(screen.getAllByText(exportedJson.risk_summary)).toHaveLength(2);

    anchorClickSpy.mockRestore();
    URL.createObjectURL = origCreateObjectURL;
    URL.revokeObjectURL = origRevokeObjectURL;
  });

  it("displays risk-floor reason, heuristic label, and not-checked badges for inconclusive/N/A detectors", async () => {
    const floorPayload = {
      job_id: "job-floor-ui",
      status: "completed",
      review_required: true,
      check_status_counts: { passed: 2, suspicious: 1, inconclusive: 1, not_applicable: 1, error: 0 },
      risk_score: 24.38,
      risk_level: "medium",
      coverage: 1.0,
      engine_runs: [
        { engine: "visual", status: "completed", finding_count: 2 },
        { engine: "file_forensics", status: "not_applicable", finding_count: 1 },
        { engine: "consistency", status: "completed", finding_count: 2 },
      ],
      findings: [
        {
          name: "copy_move",
          score: 0.65,
          confidence: 0.75,
          status: "suspicious",
          severity: "strong",
          corroborated: false,
          evidence: "Duplicated seal region detected.",
          boxes: [],
        },
        {
          name: "ela",
          score: 0.0,
          confidence: 0.0,
          status: "not_applicable",
          severity: "info",
          corroborated: false,
          evidence: "ELA not applicable to PNG.",
          boxes: [],
        },
        {
          name: "qr_code_consistency",
          score: 0.0,
          confidence: 0.0,
          status: "inconclusive",
          severity: "info",
          corroborated: false,
          evidence: "No QR detected.",
          boxes: [],
        },
      ],
      fields: {},
      field_locations: {},
      warnings: [],
      registry_checks: [],
      explanation: {
        summary: "Overall heuristic risk is medium (24.38/100, heuristic screening score, not probability of forgery).",
        reasons: [
          {
            detector: "copy_move",
            evidence: "Duplicated seal region detected. (one strong signal found; other checks clean).",
            confidence: 0.75,
            pages: [0],
          },
        ],
        limitations: ["Risk is a heuristic, not a probability of fraud or proof of authenticity."],
        recommendation: "Review highlighted evidence and verify against original records.",
        method: "deterministic",
      },
      pages: [],
    };

    vi.stubGlobal(
      "fetch",
      vi.fn((url) => {
        if (url.endsWith("/health")) return mockJsonResponse({ status: "ok" });
        if (url.endsWith("/analyze")) return mockJsonResponse({ job_id: "job-floor-ui", status: "queued" }, 202);
        if (url.includes("/result/job-floor-ui")) return mockJsonResponse(floorPayload);
        return mockJsonResponse({}, 404);
      })
    );

    render(<App />);
    await waitFor(() => expect(screen.getByText(/Backend Connected/i)).toBeInTheDocument());

    const input = document.querySelector('input[type="file"]');
    fireEvent.change(input, { target: { files: [new File(["png"], "clone.png", { type: "image/png" })] } });
    fireEvent.click(screen.getByRole("button", { name: /Analyze Document/i }));

    await waitFor(() => expect(screen.getByText("Medium Risk")).toBeInTheDocument());
    expect(screen.getAllByText(/one strong signal found; other checks clean/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/strong • independent/i)).toBeInTheDocument();
    expect(screen.getByText("Not Checked (Inconclusive)")).toBeInTheDocument();
    expect(screen.getByText("Not Checked (Not Applicable)")).toBeInTheDocument();
  });
});
