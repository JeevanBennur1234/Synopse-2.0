import {
  ShieldCheck,
  Wifi,
  WifiOff,
  RefreshCw,
  Printer,
  FlaskConical,
} from "lucide-react";
import { DEMO_SCENARIOS } from "../data/demoSamples";

export function HeaderBar({
  backendStatus,
  onRetryHealth,
  hasResult,
  onOpenReport,
  onLoadDemo,
  isDemoMode,
}) {
  const statusBadge = {
    connected: {
      icon: Wifi,
      text: "Backend Connected",
      cls: "bg-emerald-500/15 text-emerald-200 border-emerald-400/30",
    },
    offline: {
      icon: WifiOff,
      text: "Backend Offline",
      cls: "bg-red-500/15 text-red-200 border-red-400/30",
    },
    checking: {
      icon: RefreshCw,
      text: "Checking Backend...",
      cls: "bg-slate-500/20 text-slate-200 border-slate-400/30",
    },
  }[backendStatus] || {
    icon: WifiOff,
    text: "Backend Offline",
    cls: "bg-red-500/15 text-red-200 border-red-400/30",
  };

  const StatusIcon = statusBadge.icon;

  return (
    <header className="no-print bg-navy-900 text-white border-b border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-slate-800 border border-slate-700 flex items-center justify-center text-sky-400">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div>
            <div className="flex items-center gap-2.5">
              <h1 className="text-lg font-semibold tracking-tight text-white">
                Kavach
              </h1>
              <span className="text-[11px] font-medium uppercase tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                Document Forensics
              </span>
              {isDemoMode && (
                <span className="text-[11px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-amber-500/20 text-amber-200 border border-amber-400/40">
                  Demo Preview Only
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400">
              Tampered &amp; Forged Business Document Screening Workbench
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <div
            className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-md border text-xs font-medium ${statusBadge.cls}`}
            role="status"
            aria-label="Backend connection status"
          >
            <StatusIcon
              className={`h-3.5 w-3.5 ${
                backendStatus === "checking" ? "animate-spin" : ""
              }`}
            />
            <span>{statusBadge.text}</span>
            <button
              type="button"
              onClick={onRetryHealth}
              className="ml-1 text-slate-300 hover:text-white underline decoration-dotted"
              title="Re-check backend health"
            >
              Retry
            </button>
          </div>

          <div className="relative flex items-center">
            <FlaskConical className="h-3.5 w-3.5 text-slate-300 absolute left-2.5 pointer-events-none" />
            <select
              aria-label="Load isolated demo preview"
              defaultValue=""
              onChange={(e) => {
                if (e.target.value) {
                  onLoadDemo(e.target.value);
                  e.target.value = "";
                }
              }}
              className="pl-8 pr-3 py-1.5 rounded-md bg-slate-800 border border-slate-700 text-xs text-slate-200 hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500"
            >
              <option value="" disabled>
                Load Demo Preview...
              </option>
              {Object.values(DEMO_SCENARIOS).map((scenario) => (
                <option key={scenario.id} value={scenario.id}>
                  {scenario.label}
                </option>
              ))}
            </select>
          </div>

          {hasResult && (
            <button
              type="button"
              onClick={onOpenReport}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-sky-600 hover:bg-sky-500 text-xs font-medium text-white transition-colors"
            >
              <Printer className="h-3.5 w-3.5" />
              <span>Export Report</span>
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
