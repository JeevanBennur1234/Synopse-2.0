import {
  ShieldAlert,
  ShieldCheck,
  HelpCircle,
  Gauge,
  Info,
} from "lucide-react";
import { RISK_STYLES } from "../utils/forensics";

const ENGINE_LABELS = {
  visual: "Visual Forensics",
  file_forensics: "File Forensics",
  consistency: "Business Consistency",
};

const ENGINE_STATUS_CLS = {
  not_applicable: "bg-slate-50 text-slate-500 border-slate-200",
  completed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  inconclusive: "bg-slate-100 text-slate-700 border-slate-300",
  unavailable: "bg-slate-50 text-slate-500 border-slate-200",
  error: "bg-red-50 text-red-700 border-red-200",
};

export function RiskOverview({ result }) {
  const riskKey = RISK_STYLES[result.risk_level]
    ? result.risk_level
    : "inconclusive";
  const style = RISK_STYLES[riskKey];
  const hasScore =
    typeof result.risk_score === "number" && Number.isFinite(result.risk_score);
  const clampedScore = hasScore
    ? Math.max(0, Math.min(100, result.risk_score))
    : null;
  const coveragePct = Math.round(
    Math.max(0, Math.min(1, result.coverage ?? 0)) * 100
  );
  const manualReviewRequired = Boolean(
    result.review_required ||
      riskKey === "inconclusive" ||
      result.findings?.some((f) => f.status === "suspicious")
  );
  const hasStrongFloorNote = Boolean(
    result.explanation?.reasons?.some((r) =>
      /one strong signal found; other checks clean/i.test(r.evidence || "")
    )
  );

  const RiskIcon =
    riskKey === "low"
      ? ShieldCheck
      : riskKey === "inconclusive"
      ? HelpCircle
      : ShieldAlert;

  return (
    <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {manualReviewRequired && (
          <div
            role="alert"
            className="lg:col-span-12 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-xs sm:text-sm text-amber-900 font-semibold flex items-center gap-2"
          >
            <ShieldAlert className="h-4 w-4 text-amber-700 shrink-0" />
            <span>
              Manual review required. Inspect individual findings and
              limitations regardless of aggregate risk.
            </span>
          </div>
        )}
        {/* Risk Score Card */}
        <div className={`lg:col-span-5 rounded-lg border p-4 ${style.panel}`}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                Overall Risk Assessment (Heuristic, Not Probability)
              </p>
              <div className="mt-2 flex items-baseline gap-2.5">
                <span className={`text-3xl font-bold tracking-tight ${style.ring}`}>
                  {hasScore ? clampedScore.toFixed(1) : "Inconclusive"}
                </span>
                {hasScore && (
                  <span className="text-sm font-medium text-slate-500">
                    / 100
                  </span>
                )}
              </div>
            </div>
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-semibold ${style.badge}`}
            >
              <RiskIcon className="h-3.5 w-3.5" />
              <span>{style.label}</span>
            </span>
          </div>

          <div className="mt-4">
            <div className="h-2.5 w-full rounded-full bg-slate-200 overflow-hidden">
              <div
                className={`h-full transition-all duration-300 ${style.bar}`}
                style={{ width: `${hasScore ? clampedScore : 0}%` }}
              />
            </div>
            <div className="flex justify-between text-[11px] text-slate-500 mt-1">
              <span>0 (Low)</span>
              <span>35 (Medium)</span>
              <span>70 (High)</span>
              <span>100</span>
            </div>
          </div>

          <p className="mt-3 text-xs text-slate-700 leading-relaxed">
            {style.summary}
          </p>
          {hasStrongFloorNote && (
            <p className="mt-2 rounded border border-amber-300 bg-amber-50/90 px-2.5 py-1.5 text-[11px] font-medium text-amber-900">
              One strong signal found; other checks clean &mdash; risk level floored for manual review.
            </p>
          )}
        </div>

        {/* Coverage & Engine Runs */}
        <div className="lg:col-span-7 rounded-lg border border-slate-200 bg-slate-50/50 p-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Gauge className="h-4 w-4 text-slate-600" />
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-700">
                  Engine Evidence Coverage
                </h3>
              </div>
              <span className="text-sm font-bold text-slate-900">
                {coveragePct}%
              </span>
            </div>

            <div className="mt-2 h-2.5 w-full rounded-full bg-slate-200 overflow-hidden">
              <div
                className="h-full bg-navy-800 transition-all duration-300"
                style={{ width: `${coveragePct}%` }}
              />
            </div>

            <div className="mt-4 grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              {(result.engine_runs?.length
                ? result.engine_runs
                : [
                    { engine: "visual", status: "unavailable", finding_count: 0 },
                    { engine: "file_forensics", status: "unavailable", finding_count: 0 },
                    { engine: "consistency", status: "unavailable", finding_count: 0 },
                  ]
              ).map((run) => (
                <div
                  key={run.engine}
                  className="rounded-md border border-slate-200 bg-white px-3 py-2.5"
                >
                  <p className="text-xs font-medium text-slate-800">
                    {ENGINE_LABELS[run.engine] || run.engine}
                  </p>
                  <div className="mt-1.5 flex items-center justify-between gap-2">
                    <span
                      className={`text-[11px] font-medium capitalize px-2 py-0.5 rounded border ${
                        ENGINE_STATUS_CLS[run.status] ||
                        ENGINE_STATUS_CLS.unavailable
                      }`}
                    >
                      {run.status === "inconclusive"
                        ? "not checked (inconclusive)"
                        : run.status === "not_applicable"
                        ? "not checked (n/a)"
                        : String(run.status || "").replaceAll("_", " ")}
                    </span>
                    <span className="text-[11px] text-slate-500">
                      {run.finding_count}{" "}
                      {run.finding_count === 1 ? "finding" : "findings"}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-slate-200 flex items-start gap-2 text-[11px] text-slate-600">
            <Info className="h-3.5 w-3.5 text-slate-500 shrink-0 mt-0.5" />
            <span>
              {result.check_status_counts && (
                <span>
                  Individual checks:{" "}
                  {result.check_status_counts.inconclusive || 0} inconclusive,{" "}
                  {result.check_status_counts.error || 0} errors.{" "}
                </span>
              )}
              Kavach reports screening risk indicators, not definitive proof of
              forgery. At least 60% weighted detector coverage is required for a
              numeric risk score; coverage is measured across applicable engines.
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
