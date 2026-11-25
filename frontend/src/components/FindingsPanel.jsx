import { Eye, FileSearch, Calculator, Layers, MapPin } from "lucide-react";
import {
  FINDING_STATUS_STYLES,
  formatDetectorLabel,
  groupFindings,
} from "../utils/forensics";

const SECTIONS = [
  {
    key: "visual",
    title: "Visual Forensics",
    subtitle: "ELA, copy-move cloning, noise consistency, and image metadata",
    icon: Eye,
  },
  {
    key: "file_forensics",
    title: "File Forensics",
    subtitle: "PDF structure, metadata integrity, and embedded artifacts",
    icon: FileSearch,
  },
  {
    key: "consistency",
    title: "Business Consistency",
    subtitle: "GSTIN checks, tax arithmetic, totals, and running balances",
    icon: Calculator,
  },
];

export function FindingsPanel({
  findings,
  selectedFindingIndex,
  onSelectFinding,
}) {
  const grouped = groupFindings(findings);
  const sectionsToRender =
    grouped.other.length > 0
      ? [
          ...SECTIONS,
          {
            key: "other",
            title: "Additional Checks",
            subtitle: "Other registered forensic checks",
            icon: Layers,
          },
        ]
      : SECTIONS;

  return (
    <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <div className="flex items-center justify-between gap-2 mb-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Forensic Findings
          </h2>
          <p className="text-xs text-slate-500">
            Click any finding or region badge to inspect its location in the
            document viewer.
          </p>
        </div>
        <span className="text-xs font-medium px-2.5 py-1 rounded-full bg-slate-100 text-slate-700 border border-slate-200">
          {findings.length} {findings.length === 1 ? "Finding" : "Findings"}
        </span>
      </div>

      {findings.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-6 text-center">
          <p className="text-sm font-medium text-slate-700">
            No detector findings reported for this job
          </p>
          <p className="text-xs text-slate-500 mt-1">
            When forensic detectors are not yet integrated or return no results,
            Kavach leaves findings empty rather than synthesizing placeholder
            alerts.
          </p>
        </div>
      ) : (
        <div className="space-y-5">
          {sectionsToRender.map((section) => {
            const Icon = section.icon;
            const items = grouped[section.key];
            return (
              <div key={section.key}>
                <div className="flex items-center justify-between gap-2 mb-2.5">
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 text-navy-800" />
                    <div>
                      <h3 className="text-sm font-semibold text-slate-900">
                        {section.title}
                      </h3>
                      <p className="text-[11px] text-slate-500">
                        {section.subtitle}
                      </p>
                    </div>
                  </div>
                  <span className="text-xs text-slate-500">
                    {items.length}
                  </span>
                </div>

                {items.length === 0 ? (
                  <p className="text-xs text-slate-500 italic bg-slate-50 border border-slate-200 rounded-lg px-3.5 py-2.5">
                    No findings reported in this category.
                  </p>
                ) : (
                  <div className="space-y-2.5">
                    {items.map((finding) => {
                      const st =
                        FINDING_STATUS_STYLES[finding.status] ||
                        FINDING_STATUS_STYLES.inconclusive;
                      const isSelected =
                        selectedFindingIndex === finding._index;
                      const scorePct = Math.round((finding.score ?? 0) * 100);
                      const confPct = Math.round(
                        (finding.confidence ?? 0) * 100
                      );

                      return (
                        <div
                          key={`${finding.name}-${finding._index}`}
                          onClick={() => onSelectFinding(finding._index, finding.boxes?.[0] || null)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              onSelectFinding(
                                finding._index,
                                finding.boxes?.[0] || null
                              );
                            }
                          }}
                          className={`rounded-lg border p-3.5 transition-all cursor-pointer ${
                            isSelected
                              ? "border-sky-500 bg-sky-50/60 ring-1 ring-sky-500"
                              : "border-slate-200 bg-white hover:border-slate-300"
                          }`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-semibold text-slate-900">
                                {formatDetectorLabel(finding.name)}
                              </span>
                              <span
                                className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${st.badge}`}
                              >
                                {st.label}
                              </span>
                              {finding.status === "suspicious" && finding.severity && (
                                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full border border-slate-200 bg-slate-50 text-slate-700 capitalize">
                                  {finding.severity} &bull;{" "}
                                  {finding.corroborated ? "corroborated" : "independent"}
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-3 text-xs text-slate-600">
                              <span>
                                Score:{" "}
                                <strong className="text-slate-900">
                                  {scorePct}%
                                </strong>
                              </span>
                              <span>
                                Confidence:{" "}
                                <strong className="text-slate-900">
                                  {confPct}%
                                </strong>
                              </span>
                            </div>
                          </div>

                          <p className="mt-2 text-xs text-slate-700 leading-relaxed">
                            {finding.evidence}
                          </p>

                          {finding.boxes && finding.boxes.length > 0 && (
                            <div className="mt-2.5 flex flex-wrap gap-1.5">
                              {finding.boxes.map((box, bIdx) => (
                                <button
                                  key={`${box.page}-${box.x}-${box.y}-${bIdx}`}
                                  type="button"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onSelectFinding(finding._index, box);
                                  }}
                                  className="inline-flex items-center gap-1 px-2 py-1 rounded bg-red-50 hover:bg-red-100 text-red-700 border border-red-200 text-[11px] font-medium"
                                >
                                  <MapPin className="h-3 w-3" />
                                  <span>
                                    Page {box.page + 1} ({box.x}, {box.y},{" "}
                                    {box.w}x{box.h})
                                  </span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
