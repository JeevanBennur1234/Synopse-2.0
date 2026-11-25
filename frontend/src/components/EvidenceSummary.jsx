import { formatDetectorLabel } from "../utils/forensics";

export function EvidenceSummary({ result }) {
  const explanation = result?.explanation;
  const checks = result?.registry_checks || [];
  if (!explanation && !checks.length) return null;

  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm p-5 space-y-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-slate-900">
          Evidence Summary
        </h3>
        {explanation?.method && (
          <span className="text-[11px] font-medium uppercase tracking-wider px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
            {explanation.method}
          </span>
        )}
      </div>

      {explanation && (
        <div className="space-y-3">
          <p className="text-xs text-slate-700 leading-relaxed">
            {explanation.summary}
          </p>

          {(explanation.reasons || []).length > 0 && (
            <div className="space-y-2">
              {explanation.reasons.map((reason, idx) => (
                <div
                  key={`${reason.detector}-${idx}`}
                  className="border-l-2 border-amber-500 bg-amber-50/40 rounded-r px-3 py-2 text-xs"
                >
                  <strong className="text-slate-900">
                    {formatDetectorLabel(reason.detector)}
                  </strong>
                  <p className="text-slate-700 mt-0.5">{reason.evidence}</p>
                  <p className="text-[11px] text-slate-500 mt-1">
                    Confidence: {Math.round((reason.confidence ?? 0) * 100)}%
                    {reason.pages?.length
                      ? ` | Pages: ${reason.pages.map((p) => p + 1).join(", ")}`
                      : ""}
                  </p>
                </div>
              ))}
            </div>
          )}

          <p className="text-xs text-slate-800">
            <strong>Recommended action:</strong> {explanation.recommendation}
          </p>

          {(explanation.limitations || []).length > 0 && (
            <details className="text-xs text-slate-600">
              <summary className="cursor-pointer font-medium text-slate-700 hover:text-slate-900">
                Analysis limitations ({explanation.limitations.length})
              </summary>
              <ul className="list-disc pl-5 mt-1.5 space-y-1">
                {explanation.limitations.map((item, idx) => (
                  <li key={`${item}-${idx}`}>{item}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}

      <div className="border-t border-slate-200 pt-3 space-y-2">
        <div>
          <h4 className="text-xs font-semibold text-slate-900">
            Mock GST Registry (Synthetic Only)
          </h4>
          <p className="text-[11px] text-slate-500">
            Not government verification. Does not affect risk score.
          </p>
        </div>
        {checks.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {checks.map((check, idx) => (
              <div
                key={`${check.gstin}-${idx}`}
                className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
              >
                <div className="font-semibold text-slate-900 font-mono">
                  {check.gstin} &mdash;{" "}
                  <span className="font-sans capitalize">
                    {String(check.status || "").replaceAll("_", " ")}
                  </span>
                </div>
                <p className="text-slate-600 mt-0.5">{check.message}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No registry lookup results.</p>
        )}
      </div>
    </section>
  );
}
