import { formatDetectorLabel } from "../utils/forensics";
export function EvidenceSummary({ result }) {
  const e = result.explanation;
  const checks = result.registry_checks || [];
  if (!e && !checks.length) return null;
  return <section className="rounded-xl border border-slate-200 bg-white p-4 space-y-3 text-sm">
    <h3 className="font-bold text-slate-900">Evidence summary</h3>
    {e && <>
      <p>{e.summary}</p>
      {(e.reasons || []).map((r,i)=><div key={i} className="border-l-2 border-amber-400 pl-3">
        <strong>{formatDetectorLabel(r.detector)}</strong>
        <p>{r.evidence}</p>
        <p className="text-xs text-slate-500">Confidence: {Math.round(r.confidence*100)}%{r.pages?.length ? " | Pages: "+r.pages.map(p=>p+1).join(", ") : ""}</p>
      </div>)}
      <p><strong>Recommended action:</strong> {e.recommendation}</p>
      <details><summary>Analysis limitations</summary><ul className="list-disc pl-5">{(e.limitations || []).map((l,i)=><li key={i}>{l}</li>)}</ul></details>
    </>}
    <h4 className="font-semibold">Mock GST registry (synthetic only)</h4>
    <p className="text-xs text-slate-600">Not government verification. Does not affect risk score.</p>
    {checks.length ? checks.map((c,i)=><div key={i} className="rounded border p-2"><strong>{c.gstin}</strong> — {c.status.replaceAll("_"," ")}<p>{c.message}</p></div>) : <p>No registry lookup results.</p>}
  </section>;
}

