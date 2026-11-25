import { AlertTriangle, FileSpreadsheet, MapPin } from "lucide-react";
import { formatFieldLabel } from "../utils/forensics";

export function FieldsAndWarnings({
  fields = {},
  fieldLocations = {},
  warnings = [],
  onLocateField,
}) {
  const fieldEntries = Object.entries(fields).filter(
    ([, values]) => Array.isArray(values) && values.length > 0
  );

  return (
    <div className="space-y-5">
      {/* Extracted Financial Fields */}
      <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 text-navy-800" />
            <h2 className="text-base font-semibold text-slate-900">
              Extracted Financial Fields
            </h2>
          </div>
          <span className="text-xs text-slate-500">
            {fieldEntries.length} fields
          </span>
        </div>

        {fieldEntries.length === 0 ? (
          <p className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg p-3.5">
            No structured financial fields were extracted from this document.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {fieldEntries.map(([key, values]) => {
              const locs = fieldLocations?.[key] || [];
              const firstLoc = locs[0];
              return (
                <div
                  key={key}
                  className="rounded-lg border border-slate-200 bg-slate-50/60 px-3 py-2.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                      {formatFieldLabel(key)}
                    </span>
                    {firstLoc && onLocateField && (
                      <button
                        type="button"
                        onClick={() => onLocateField(firstLoc)}
                        className="inline-flex items-center gap-1 text-[11px] text-sky-700 hover:text-sky-900 font-medium"
                        title={`Highlight on page ${firstLoc.page + 1}`}
                      >
                        <MapPin className="h-3 w-3" />
                        <span>P{firstLoc.page + 1}</span>
                      </button>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {values.map((val, idx) => (
                      <span
                        key={`${key}-${idx}`}
                        className="font-mono text-xs font-semibold text-slate-900 bg-white px-2 py-0.5 rounded border border-slate-200"
                      >
                        {val}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Processing Warnings */}
      <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-600" />
            <h2 className="text-base font-semibold text-slate-900">
              Processing Warnings &amp; Limitations
            </h2>
          </div>
          <span className="text-xs text-slate-500">{warnings.length}</span>
        </div>

        {warnings.length === 0 ? (
          <p className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg p-3.5">
            No processing warnings recorded.
          </p>
        ) : (
          <ul className="space-y-2">
            {warnings.map((warning, idx) => (
              <li
                key={`${warning}-${idx}`}
                className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-xs text-amber-900"
              >
                <AlertTriangle className="h-3.5 w-3.5 text-amber-600 shrink-0 mt-0.5" />
                <span>{warning}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
