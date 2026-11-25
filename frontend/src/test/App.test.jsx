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
});
