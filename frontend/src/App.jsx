import { useCallback, useEffect, useRef, useState } from "react";
import { checkHealth, getJobResult, uploadDocument } from "./api/client";
import { DEMO_SCENARIOS } from "./data/demoSamples";
import { HeaderBar } from "./components/HeaderBar";
import { UploadPanel } from "./components/UploadPanel";
import { RiskOverview } from "./components/RiskOverview";
import { FindingsPanel } from "./components/FindingsPanel";
import { FieldsAndWarnings } from "./components/FieldsAndWarnings";
import { DocumentViewer } from "./components/DocumentViewer";
import { PrintableReport } from "./components/PrintableReport";

const POLL_INTERVAL_MS = 1000;

export function App() {
  const [backendStatus, setBackendStatus] = useState("checking");
  const [selectedFile, setSelectedFile] = useState(null);
  const [activeFilename, setActiveFilename] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadError, setUploadError] = useState(null);

  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [result, setResult] = useState(null);
  const [isDemoMode, setIsDemoMode] = useState(false);

  const [currentPage, setCurrentPage] = useState(0);
  const [selectedFindingIndex, setSelectedFindingIndex] = useState(null);
  const [highlightedBox, setHighlightedBox] = useState(null);
  const [showReportModal, setShowReportModal] = useState(false);

  const pollTimerRef = useRef(null);
  const pollAbortRef = useRef(null);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    if (pollAbortRef.current) {
      pollAbortRef.current.abort();
      pollAbortRef.current = null;
    }
  }, []);

  const verifyBackendHealth = useCallback(async () => {
    setBackendStatus("checking");
    const controller = new AbortController();
    try {
      const data = await checkHealth(controller.signal);
      setBackendStatus(data?.status === "ok" ? "connected" : "offline");
    } catch {
      setBackendStatus("offline");
    }
  }, []);

  useEffect(() => {
    verifyBackendHealth();
    return () => stopPolling();
  }, [verifyBackendHealth, stopPolling]);

  const pollJob = useCallback(
    (targetJobId) => {
      stopPolling();
      let active = true;

      const tick = async () => {
        if (!active) return;
        const controller = new AbortController();
        pollAbortRef.current = controller;

        try {
          const data = await getJobResult(targetJobId, controller.signal);
          if (!active) return;

          setJobStatus(data.status);
          if (data.status === "completed") {
            setResult(data);
            setCurrentPage(0);
            setSelectedFindingIndex(null);
            setHighlightedBox(null);
            stopPolling();
            return;
          }
          if (data.status === "failed") {
            setResult(data);
            setUploadError(
              data.warnings?.[0] || "Document analysis failed on the backend."
            );
            stopPolling();
            return;
          }

          pollTimerRef.current = setTimeout(tick, POLL_INTERVAL_MS);
        } catch (err) {
          if (!active || err?.name === "AbortError") return;
          setUploadError(err?.message || "Lost connection while polling job.");
          setJobStatus("failed");
          stopPolling();
        }
      };

      tick();
      return () => {
        active = false;
        stopPolling();
      };
    },
    [stopPolling]
  );

  async function handleAnalyze() {
    if (!selectedFile || isSubmitting) return;
    stopPolling();
    setIsDemoMode(false);
    setIsSubmitting(true);
    setUploadError(null);
    setResult(null);
    setSelectedFindingIndex(null);
    setHighlightedBox(null);
    setCurrentPage(0);

    try {
      const accepted = await uploadDocument(selectedFile);
      setActiveFilename(selectedFile.name);
      setJobId(accepted.job_id);
      setJobStatus(accepted.status || "queued");
      pollJob(accepted.job_id);
    } catch (err) {
      setUploadError(err?.message || "Failed to upload document.");
      setJobStatus(null);
      setJobId(null);
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleLoadDemo(scenarioId) {
    const scenario = DEMO_SCENARIOS[scenarioId];
    if (!scenario) return;
    stopPolling();
    setIsDemoMode(true);
    setUploadError(null);
    setActiveFilename(scenario.filename);
    setJobId(scenario.result.job_id);
    setJobStatus(scenario.result.status);
    setResult(scenario.result);
    setCurrentPage(0);
    setSelectedFindingIndex(null);
    setHighlightedBox(null);
  }

  function handleSelectFinding(findingIndex, box) {
    setSelectedFindingIndex(findingIndex);
    if (box) {
      setCurrentPage(box.page ?? 0);
      setHighlightedBox(box);
    } else {
      setHighlightedBox(null);
    }
  }

  function handleLocateField(loc) {
    setSelectedFindingIndex(null);
    setCurrentPage(loc.page ?? 0);
    setHighlightedBox({ ...loc, isFieldLocation: true });
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <HeaderBar
        backendStatus={backendStatus}
        onRetryHealth={verifyBackendHealth}
        hasResult={Boolean(result && result.status === "completed")}
        onOpenReport={() => setShowReportModal(true)}
        onLoadDemo={handleLoadDemo}
        isDemoMode={isDemoMode}
      />

      <main className="no-print flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        {isDemoMode && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-xs text-amber-900 flex items-center justify-between gap-2">
            <span>
              <strong>Demo Preview Mode:</strong> Displaying isolated sample
              data (<code className="font-mono">{activeFilename}</code>). This is
              not a live backend result.
            </span>
            <button
              type="button"
              onClick={() => {
                setIsDemoMode(false);
                setResult(null);
                setJobId(null);
                setJobStatus(null);
              }}
              className="underline font-semibold hover:text-amber-950"
            >
              Exit Demo
            </button>
          </div>
        )}

        <UploadPanel
          selectedFile={selectedFile}
          onSelectFile={(file) => {
            setSelectedFile(file);
            setUploadError(null);
          }}
          onClearFile={() => {
            setSelectedFile(null);
            setUploadError(null);
          }}
          onAnalyze={handleAnalyze}
          backendStatus={backendStatus}
          jobStatus={jobStatus}
          jobId={jobId}
          uploadError={uploadError}
          isSubmitting={isSubmitting}
        />

        {result && result.status === "completed" && (
          <>
            <RiskOverview result={result} />

            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
              <div className="xl:col-span-5 space-y-6">
                <FindingsPanel
                  findings={result.findings || []}
                  selectedFindingIndex={selectedFindingIndex}
                  onSelectFinding={handleSelectFinding}
                />
                <FieldsAndWarnings
                  fields={result.fields}
                  fieldLocations={result.field_locations}
                  warnings={result.warnings}
                  onLocateField={handleLocateField}
                />
              </div>

              <div className="xl:col-span-7">
                <DocumentViewer
                  pages={result.pages || []}
                  findings={result.findings || []}
                  currentPage={currentPage}
                  onChangePage={setCurrentPage}
                  selectedFindingIndex={selectedFindingIndex}
                  highlightedBox={highlightedBox}
                  onSelectBox={handleSelectFinding}
                />
              </div>
            </div>
          </>
        )}
      </main>

      {showReportModal && result && (
        <PrintableReport
          result={result}
          filename={activeFilename}
          isDemoMode={isDemoMode}
          onClose={() => setShowReportModal(false)}
        />
      )}
    </div>
  );
}

export default App;
