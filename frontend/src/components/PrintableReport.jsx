import { useEffect, useRef, useState } from "react";
import { Download, Printer, X, ShieldCheck } from "lucide-react";
import { resolveAssetUrl } from "../api/client";
import {
  FINDING_STATUS_STYLES,
  RISK_STYLES,
  formatDetectorLabel,
  formatFieldLabel,
} from "../utils/forensics";
import { EvidenceSummary } from "./EvidenceSummary";

function RegionPreview({ page, box, label }) {
  const canvasRef = useRef(null);
  const [rendered, setRendered] = useState(false);

  useEffect(() => {
    if (!page?.preview_url || !box) return undefined;
    let cancelled = false;
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      if (cancelled || !canvasRef.current) return;
      const pad = 40;
      const sx = Math.max(0, box.x - pad);
      const sy = Math.max(0, box.y - pad);
      const sw = Math.min(img.width - sx, box.w + pad * 2);
      const sh = Math.min(img.height - sy, box.h + pad * 2);
      if (sw <= 0 || sh <= 0) return;

      const targetW = 260;
      const scale = targetW / sw;
      const targetH = Math.max(60, Math.round(sh * scale));

      const canvas = canvasRef.current;
      canvas.width = targetW;
      canvas.height = targetH;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      ctx.drawImage(img, sx, sy, sw, sh, 0, 0, targetW, targetH);
      ctx.strokeStyle = "#dc2626";
      ctx.lineWidth = 2;
      ctx.strokeRect(
        (box.x - sx) * scale,
        (box.y - sy) * scale,
        box.w * scale,
        box.h * scale
      );
      setRendered(true);
    };
    img.src = resolveAssetUrl(page.preview_url);
    return () => {
      cancelled = true;
    };
  }, [page?.preview_url, box]);

  return (
    <div className="rounded border border-slate-200 bg-slate-50 p-2">
      <p className="text-[11px] font-medium text-slate-700 mb-1.5">
        {label} &bull; Page {box.page + 1} ({box.x}, {box.y}, {box.w}&times;
        {box.h})
      </p>
      <canvas
        ref={canvasRef}
        className={`rounded border border-slate-200 bg-white max-w-full ${
          rendered ? "block" : "hidden"
        }`}
      />
      {!rendered && (
        <div className="text-[11px] text-slate-500 font-mono bg-white border border-dashed border-slate-300 rounded px-2.5 py-2">
          Region coordinates: page {box.page + 1}, x={box.x}, y={box.y}, w={box.w}, h={box.h}
        </div>
      )}
    </div>
  );
}

export function PrintableReport({ result, filename, isDemoMode, onClose }) {
  const riskKey = RISK_STYLES[result.risk_level]
    ? result.risk_level
    : "inconclusive";
  const riskStyle = RISK_STYLES[riskKey];
  const hasScore =
    typeof result.risk_score === "number" && Number.isFinite(result.risk_score);
  const coveragePct = Math.round(
    Math.max(0, Math.min(1, result.coverage ?? 0)) * 100
  );

  const regionItems = [];
  (result.findings || []).forEach((finding, fIdx) => {
    const boxes =
      finding.status === "suspicious" ? finding.boxes || [] : [];
    boxes.forEach((box, bIdx) => {
      const page = (result.pages || []).find((p) => p.page === box.page);
      regionItems.push({
        key: `${fIdx}-${bIdx}`,
        page,
        box,
        label: formatDetectorLabel(finding.name),
      });
    });
  });

  function handleDownloadJson() {
    const payload = {
      generated_at: new Date().toISOString(),
      demo_preview: Boolean(isDemoMode),
      filename: filename || "uploaded-document",
      ...result,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `kavach-report-${result.job_id}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/60 overflow-y-auto p-4 sm:p-8 print:static print:bg-white print:p-0">
      <div className="max-w-4xl mx-auto bg-white rounded-xl shadow-xl border border-slate-200 overflow-hidden print:shadow-none print:border-0 print:rounded-none">
        {/* Modal Toolbar (hidden when printing) */}
        <div className="no-print flex flex-wrap items-center justify-between gap-3 bg-slate-100 px-5 py-3 border-b border-slate-200">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-700">
            <ShieldCheck className="h-4 w-4 text-navy-800" />
            <span>Kavach Forensic Analysis Report Preview</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleDownloadJson}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-slate-300 bg-white hover:bg-slate-50 text-xs font-medium text-slate-700"
            >
              <Download className="h-3.5 w-3.5" />
              <span>Download JSON</span>
            </button>
            <button
              type="button"
              onClick={() => window.print()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-navy-900 hover:bg-navy-800 text-xs font-semibold text-white"
            >
              <Printer className="h-3.5 w-3.5" />
              <span>Print / Save PDF</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close report preview"
              className="p-1.5 rounded-md text-slate-500 hover:bg-slate-200"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Printable Report Body */}
        <div className="p-6 sm:p-8 space-y-6 text-slate-900">
          <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 pb-4">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Kavach &bull; Business Document Screening Report
              </p>
              <h2 className="text-xl font-bold text-slate-900 mt-1">
                {filename || "Analyzed Document"}
              </h2>
              <p className="text-xs text-slate-500 mt-1 font-mono">
                Job ID: {result.job_id} &bull; Status: {result.status} &bull;
                Generated: {new Date().toLocaleString()}
              </p>
            </div>
            <div className="text-right">
              <span
                className={`inline-block px-3 py-1 rounded-full border text-xs font-semibold ${riskStyle.badge}`}
              >
                {riskStyle.label}
              </span>
              {isDemoMode && (
                <p className="mt-1.5 text-[11px] font-semibold text-amber-700">
                  DEMO PREVIEW — NOT REAL ANALYSIS
                </p>
              )}
            </div>
          </div>

          {/* Summary Metrics */}
          <div className="grid grid-cols-3 gap-4 print-break-inside-avoid">
            <div className="rounded-lg border border-slate-200 p-3.5">
              <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
                Risk Score
              </p>
              <p className="text-xl font-bold mt-1">
                {hasScore ? `${result.risk_score.toFixed(1)} / 100` : "Inconclusive"}
              </p>
            </div>
            <div className="rounded-lg border border-slate-200 p-3.5">
              <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
                Analysis Coverage
              </p>
              <p className="text-xl font-bold mt-1">{coveragePct}%</p>
            </div>
            <div className="rounded-lg border border-slate-200 p-3.5">
              <p className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
                Pages / Findings
              </p>
              <p className="text-xl font-bold mt-1">
                {(result.pages || []).length} / {(result.findings || []).length}
              </p>
            </div>
          </div>

          <EvidenceSummary result={result} />

          {/* Findings */}
          <div className="print-break-inside-avoid">
            <h3 className="text-sm font-bold text-slate-900 mb-2">
              Findings &amp; Evidence
            </h3>
            {!result.findings || result.findings.length === 0 ? (
              <p className="text-xs text-slate-600 border border-slate-200 rounded-lg p-3">
                No detector findings recorded for this job.
              </p>
            ) : (
              <div className="space-y-2.5">
                {result.findings.map((f, idx) => {
                  const st =
                    FINDING_STATUS_STYLES[f.status] ||
                    FINDING_STATUS_STYLES.inconclusive;
                  return (
                    <div
                      key={`${f.name}-${idx}`}
                      className="rounded-lg border border-slate-200 p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-slate-900">
                          {formatDetectorLabel(f.name)}
                        </span>
                        <span className="text-[11px] text-slate-600">
                          Status: <strong>{st.label}</strong> &bull; Score:{" "}
                          {Math.round((f.score ?? 0) * 100)}% &bull; Confidence:{" "}
                          {Math.round((f.confidence ?? 0) * 100)}%
                        </span>
                      </div>
                      <p className="text-xs text-slate-700 mt-1">{f.evidence}</p>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Suspicious Region Previews */}
          {regionItems.length > 0 && (
            <div className="print-break-inside-avoid">
              <h3 className="text-sm font-bold text-slate-900 mb-2">
                Suspicious Region Previews
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {regionItems.map((item) => (
                  <RegionPreview
                    key={item.key}
                    page={item.page}
                    box={item.box}
                    label={item.label}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Extracted Fields */}
          {result.fields && Object.keys(result.fields).length > 0 && (
            <div className="print-break-inside-avoid">
              <h3 className="text-sm font-bold text-slate-900 mb-2">
                Extracted Financial Fields
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                {Object.entries(result.fields)
                  .filter(([, vals]) => Array.isArray(vals) && vals.length > 0)
                  .map(([key, vals]) => (
                    <div
                      key={key}
                      className="rounded border border-slate-200 px-2.5 py-2"
                    >
                      <span className="text-[10px] uppercase text-slate-500 block">
                        {formatFieldLabel(key)}
                      </span>
                      <span className="font-mono font-semibold text-slate-900">
                        {vals.join(", ")}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Warnings & Limitations */}
          <div className="print-break-inside-avoid border-t border-slate-200 pt-4">
            <h3 className="text-sm font-bold text-slate-900 mb-2">
              Limitations &amp; Processing Warnings
            </h3>
            <ul className="list-disc pl-5 text-xs text-slate-700 space-y-1">
              {(result.warnings || []).map((w, idx) => (
                <li key={`${w}-${idx}`}>{w}</li>
              ))}
              <li>
                Screening scores indicate potential anomalies requiring human
                review and do not constitute legal proof of forgery.
              </li>
              <li>
                Missing or unavailable detector checks are treated as
                inconclusive rather than clean results.
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
