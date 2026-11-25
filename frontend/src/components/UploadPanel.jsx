import { useRef, useState } from "react";
import {
  UploadCloud,
  FileText,
  X,
  AlertCircle,
  Loader2,
  CheckCircle2,
  SearchCheck,
} from "lucide-react";
import { formatBytes, validateSelectedFile } from "../utils/forensics";

export function UploadPanel({
  selectedFile,
  onSelectFile,
  onClearFile,
  onAnalyze,
  backendStatus,
  jobStatus,
  jobId,
  uploadError,
  isSubmitting,
}) {
  const inputRef = useRef(null);
  const [isDragging, setIsDragging] = useState(false);
  const [validationError, setValidationError] = useState(null);

  const isBusy =
    isSubmitting || jobStatus === "queued" || jobStatus === "running";

  function handleCandidateFile(file) {
    if (!file) return;
    const check = validateSelectedFile(file);
    if (!check.valid) {
      setValidationError(check.error);
      onClearFile();
      return;
    }
    setValidationError(null);
    onSelectFile(file);
  }

  function handleDrop(event) {
    event.preventDefault();
    setIsDragging(false);
    if (isBusy) return;
    const file = event.dataTransfer?.files?.[0];
    handleCandidateFile(file);
  }

  const displayedError = validationError || uploadError;

  return (
    <section className="no-print bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Document Submission
          </h2>
          <p className="text-xs text-slate-500">
            Upload an invoice, receipt, or bank statement (PDF, PNG, or JPEG up
            to 15 MB) for automated screening.
          </p>
        </div>
        {jobId && (
          <span className="text-xs font-mono px-2.5 py-1 rounded bg-slate-100 text-slate-700 border border-slate-200">
            Job: {jobId}
          </span>
        )}
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!isBusy) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => {
          if (!isBusy) inputRef.current?.click();
        }}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if ((e.key === "Enter" || e.key === " ") && !isBusy) {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        aria-label="Drop document here or click to browse"
        className={`rounded-lg border-2 border-dashed p-6 text-center transition-colors cursor-pointer ${
          isDragging
            ? "border-sky-500 bg-sky-50/70"
            : "border-slate-300 hover:border-slate-400 bg-slate-50/60"
        } ${isBusy ? "opacity-60 cursor-not-allowed" : ""}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"
          className="hidden"
          disabled={isBusy}
          onChange={(e) => {
            handleCandidateFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
        <UploadCloud className="h-8 w-8 text-slate-500 mx-auto mb-2" />
        <p className="text-sm font-medium text-slate-800">
          Drag and drop a business document here, or{" "}
          <span className="text-sky-700 underline">browse files</span>
        </p>
        <p className="text-xs text-slate-500 mt-1">
          Accepted formats: PDF, PNG, JPEG &bull; Max size: 15 MB &bull; Use
          synthetic or consented documents only
        </p>
      </div>

      {selectedFile && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-9 w-9 rounded-md bg-navy-800 text-white flex items-center justify-center shrink-0">
              <FileText className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-medium text-slate-900 truncate">
                {selectedFile.name}
              </p>
              <p className="text-xs text-slate-500">
                {formatBytes(selectedFile.size)} &bull;{" "}
                {selectedFile.type || "Document"}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {!isBusy && (
              <button
                type="button"
                onClick={() => {
                  setValidationError(null);
                  onClearFile();
                }}
                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-slate-300 bg-white text-xs font-medium text-slate-700 hover:bg-slate-100"
              >
                <X className="h-3.5 w-3.5" />
                <span>Clear</span>
              </button>
            )}
            <button
              type="button"
              onClick={onAnalyze}
              disabled={isBusy || backendStatus === "offline"}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-navy-900 hover:bg-navy-800 disabled:bg-slate-300 disabled:text-slate-600 text-xs font-semibold text-white transition-colors"
            >
              {isBusy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span>
                    {jobStatus === "running"
                      ? "Analyzing Document..."
                      : jobStatus === "queued"
                      ? "Queued..."
                      : "Uploading..."}
                  </span>
                </>
              ) : (
                <>
                  <SearchCheck className="h-4 w-4" />
                  <span>Analyze Document</span>
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {backendStatus === "offline" && (
        <div
          role="alert"
          className="mt-3 flex items-start gap-2.5 rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-xs text-amber-900"
        >
          <AlertCircle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold">Backend server unreachable.</span>{" "}
            Start FastAPI at <code className="font-mono">http://localhost:8000</code>{" "}
            or select a <span className="font-semibold">Demo Preview</span> from
            the header to explore the UI offline.
          </div>
        </div>
      )}

      {displayedError && (
        <div
          role="alert"
          className="mt-3 flex items-start gap-2.5 rounded-lg border border-red-200 bg-red-50 px-3.5 py-2.5 text-xs text-red-800"
        >
          <AlertCircle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
          <span>{displayedError}</span>
        </div>
      )}

      {jobStatus && (
        <div
          className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-600"
          aria-live="polite"
        >
          <span className="font-medium text-slate-700">Pipeline Status:</span>
          {["queued", "running", "completed"].map((step) => {
            const active = jobStatus === step;
            const failed = jobStatus === "failed" && step === "running";
            const done =
              (jobStatus === "running" && step === "queued") ||
              jobStatus === "completed";
            return (
              <span
                key={step}
                className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full border capitalize ${
                  failed
                    ? "bg-red-50 text-red-700 border-red-200 font-semibold"
                    : active
                    ? "bg-sky-50 text-sky-800 border-sky-200 font-semibold"
                    : done
                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                    : "bg-slate-50 text-slate-400 border-slate-200"
                }`}
              >
                {done && !failed && <CheckCircle2 className="h-3 w-3" />}
                {active && step !== "completed" && (
                  <Loader2 className="h-3 w-3 animate-spin" />
                )}
                {failed ? "failed" : step}
              </span>
            );
          })}
          {jobStatus === "failed" && (
            <span className="px-2.5 py-0.5 rounded-full border bg-red-50 text-red-700 border-red-200 font-semibold">
              Failed
            </span>
          )}
        </div>
      )}
    </section>
  );
}
