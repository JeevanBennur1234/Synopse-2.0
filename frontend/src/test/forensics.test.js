import { describe, expect, it } from "vitest";
import {
  categorizeFinding,
  formatBytes,
  groupFindings,
  scaleBoundingBox,
  validateSelectedFile,
} from "../utils/forensics";

describe("validateSelectedFile", () => {
  it("accepts valid PDF, PNG, and JPEG files", () => {
    const pdf = new File(["%PDF-1.4"], "invoice.pdf", { type: "application/pdf" });
    const png = new File(["png"], "scan.png", { type: "image/png" });
    const jpg = new File(["jpg"], "photo.jpg", { type: "image/jpeg" });

    expect(validateSelectedFile(pdf).valid).toBe(true);
    expect(validateSelectedFile(png).valid).toBe(true);
    expect(validateSelectedFile(jpg).valid).toBe(true);
  });

  it("rejects unsupported file types and empty files", () => {
    const txt = new File(["hello"], "notes.txt", { type: "text/plain" });
    const empty = new File([], "empty.pdf", { type: "application/pdf" });

    expect(validateSelectedFile(txt).valid).toBe(false);
    expect(validateSelectedFile(txt).error).toMatch(/Unsupported/i);
    expect(validateSelectedFile(empty).valid).toBe(false);
    expect(validateSelectedFile(empty).error).toMatch(/empty/i);
  });

  it("rejects files over 15 MB", () => {
    const bigFile = new File(["x"], "huge.pdf", { type: "application/pdf" });
    Object.defineProperty(bigFile, "size", { value: 16 * 1024 * 1024 });

    const res = validateSelectedFile(bigFile);
    expect(res.valid).toBe(false);
    expect(res.error).toMatch(/15 MB/i);
  });
});

describe("scaleBoundingBox", () => {
  it("scales original page pixel boxes proportionally when display image is resized", () => {
    const box = { page: 0, x: 600, y: 800, w: 300, h: 100 };
    const scaledHalf = scaleBoundingBox(box, 1200, 1600, 600, 800);
    expect(scaledHalf).toEqual({ left: 300, top: 400, width: 150, height: 50 });

    const scaledZoom = scaleBoundingBox(box, 1200, 1600, 1500, 2000);
    expect(scaledZoom).toEqual({ left: 750, top: 1000, width: 375, height: 125 });
  });

  it("returns null if dimensions are missing", () => {
    expect(scaleBoundingBox({ page: 0, x: 1, y: 1, w: 10, h: 10 }, 0, 100, 50, 50)).toBeNull();
  });
});

describe("finding categorization & byte formatting", () => {
  it("groups Phase 13 detector names into visual, file_forensics, and consistency", () => {
    expect(categorizeFinding("ela")).toBe("visual");
    expect(categorizeFinding("copy_move")).toBe("visual");
    expect(categorizeFinding("image_metadata")).toBe("visual");
    expect(categorizeFinding("file_forensics")).toBe("file_forensics");
    expect(categorizeFinding("pdf_metadata_integrity")).toBe("file_forensics");
    expect(categorizeFinding("consistency")).toBe("consistency");
    expect(categorizeFinding("invoice_line_items_arithmetic")).toBe("consistency");
    expect(categorizeFinding("calendar_date_validity")).toBe("consistency");
    expect(categorizeFinding("ifsc_validation")).toBe("consistency");
    expect(categorizeFinding("qr_code_consistency")).toBe("consistency");

    const grouped = groupFindings([
      { name: "ela", score: 0.8, confidence: 0.9, status: "suspicious", evidence: "x", boxes: [] },
      { name: "pdf_metadata_integrity", score: 0.1, confidence: 0.9, status: "passed", evidence: "y", boxes: [] },
      { name: "invoice_line_items_arithmetic", score: 0.9, confidence: 0.95, status: "suspicious", evidence: "z", boxes: [] },
    ]);

    expect(grouped.visual).toHaveLength(1);
    expect(grouped.file_forensics).toHaveLength(1);
    expect(grouped.consistency).toHaveLength(1);
    expect(grouped.other).toHaveLength(0);
  });

  it("formats file sizes clearly", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(2 * 1024 * 1024)).toBe("2.00 MB");
  });
});
