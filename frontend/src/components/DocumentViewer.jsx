import { useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Eye,
  EyeOff,
  Maximize2,
} from "lucide-react";
import { resolveAssetUrl } from "../api/client";
import { formatDetectorLabel, scaleBoundingBox } from "../utils/forensics";

const ZOOM_LEVELS = [0.6, 0.8, 1.0, 1.25, 1.5];

export function DocumentViewer({
  pages = [],
  findings = [],
  currentPage,
  onChangePage,
  selectedFindingIndex,
  highlightedBox,
  onSelectBox,
}) {
  const [zoom, setZoom] = useState(1.0);
  const [showOverlays, setShowOverlays] = useState(true);
  const [displaySize, setDisplaySize] = useState({ width: 0, height: 0 });
  const imgRef = useRef(null);

  const activePage =
    pages.find((p) => p.page === currentPage) || pages[0] || null;
  const pageIndex = activePage ? activePage.page : 0;

  useEffect(() => {
    const img = imgRef.current;
    if (!img) return undefined;

    const updateSize = () => {
      if (imgRef.current) {
        setDisplaySize({
          width: imgRef.current.clientWidth,
          height: imgRef.current.clientHeight,
        });
      }
    };

    updateSize();
    const rafId =
      typeof requestAnimationFrame === "function"
        ? requestAnimationFrame(updateSize)
        : null;

    let observer;
    if (typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(updateSize);
      observer.observe(img);
    } else {
      window.addEventListener("resize", updateSize);
    }
    return () => {
      if (rafId !== null && typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(rafId);
      }
      if (observer) {
        observer.disconnect();
      } else {
        window.removeEventListener("resize", updateSize);
      }
    };
  }, [activePage?.preview_url, zoom]);

  const pageBoxes = [];
  if (activePage) {
    findings.forEach((finding, fIndex) => {
      (finding.boxes || []).forEach((box, bIndex) => {
        if (box.page === pageIndex) {
          pageBoxes.push({
            box,
            finding,
            findingIndex: fIndex,
            boxIndex: bIndex,
          });
        }
      });
    });
  }

  const canPrev = pages.length > 1 && pageIndex > 0;
  const canNext = pages.length > 1 && pageIndex < pages.length - 1;

  return (
    <section className="bg-white rounded-xl border border-slate-200 shadow-sm p-5 flex flex-col">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Interactive Document Viewer
          </h2>
          {activePage && (
            <p className="text-xs text-slate-500">
              Page {pageIndex + 1} of {pages.length} &bull;{" "}
              {activePage.width} &times; {activePage.height} px &bull;
              Extraction:{" "}
              <span className="font-medium uppercase">
                {activePage.method === "native_pdf" ? "Native PDF" : "OCR"}
              </span>
            </p>
          )}
        </div>

        <div className="no-print flex flex-wrap items-center gap-2">
          {/* Pagination */}
          <div className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50">
            <button
              type="button"
              onClick={() => onChangePage(Math.max(0, pageIndex - 1))}
              disabled={!canPrev}
              aria-label="Previous page"
              className="p-1.5 text-slate-700 hover:bg-slate-200/70 disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="px-2.5 text-xs font-medium text-slate-700">
              {pages.length ? `${pageIndex + 1} / ${pages.length}` : "0 / 0"}
            </span>
            <button
              type="button"
              onClick={() =>
                onChangePage(Math.min(pages.length - 1, pageIndex + 1))
              }
              disabled={!canNext}
              aria-label="Next page"
              className="p-1.5 text-slate-700 hover:bg-slate-200/70 disabled:opacity-40"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>

          {/* Zoom Controls */}
          <div className="inline-flex items-center rounded-md border border-slate-200 bg-slate-50">
            <button
              type="button"
              onClick={() => {
                const idx = ZOOM_LEVELS.indexOf(zoom);
                if (idx > 0) setZoom(ZOOM_LEVELS[idx - 1]);
              }}
              disabled={zoom <= ZOOM_LEVELS[0]}
              aria-label="Zoom out"
              className="p-1.5 text-slate-700 hover:bg-slate-200/70 disabled:opacity-40"
            >
              <ZoomOut className="h-4 w-4" />
            </button>
            <span className="px-2 text-xs font-medium text-slate-700 min-w-[48px] text-center">
              {Math.round(zoom * 100)}%
            </span>
            <button
              type="button"
              onClick={() => {
                const idx = ZOOM_LEVELS.indexOf(zoom);
                if (idx < ZOOM_LEVELS.length - 1) setZoom(ZOOM_LEVELS[idx + 1]);
              }}
              disabled={zoom >= ZOOM_LEVELS[ZOOM_LEVELS.length - 1]}
              aria-label="Zoom in"
              className="p-1.5 text-slate-700 hover:bg-slate-200/70 disabled:opacity-40"
            >
              <ZoomIn className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={() => setZoom(1.0)}
              aria-label="Reset zoom"
              title="Reset zoom to 100%"
              className="p-1.5 text-slate-600 hover:bg-slate-200/70 border-l border-slate-200"
            >
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          </div>

          {/* Overlay Toggle */}
          <button
            type="button"
            onClick={() => setShowOverlays((prev) => !prev)}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border text-xs font-medium transition-colors ${
              showOverlays
                ? "bg-red-50 text-red-700 border-red-200"
                : "bg-slate-50 text-slate-600 border-slate-200"
            }`}
          >
            {showOverlays ? (
              <Eye className="h-3.5 w-3.5" />
            ) : (
              <EyeOff className="h-3.5 w-3.5" />
            )}
            <span>
              {showOverlays
                ? `Regions (${pageBoxes.length})`
                : "Regions Hidden"}
            </span>
          </button>
        </div>
      </div>

      {!activePage ? (
        <div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-10 text-center text-xs text-slate-500">
          No rendered pages available yet.
        </div>
      ) : (
        <div className="rounded-lg border border-slate-200 bg-slate-100 overflow-auto max-h-[760px] p-4">
          <div
            className="relative block mx-auto shadow-md bg-white"
            style={{ width: `${Math.round(zoom * 100)}%`, maxWidth: `${Math.round(activePage.width * zoom)}px` }}
          >
            <img
              ref={imgRef}
              src={resolveAssetUrl(activePage.preview_url)}
              alt={`Document page ${pageIndex + 1}`}
              onLoad={() => {
                if (imgRef.current) {
                  setDisplaySize({
                    width: imgRef.current.clientWidth,
                    height: imgRef.current.clientHeight,
                  });
                }
              }}
              className="block w-full h-auto select-none"
            />

            {showOverlays &&
              displaySize.width > 0 &&
              displaySize.height > 0 &&
              pageBoxes.map(({ box, finding, findingIndex, boxIndex }) => {
                const scaled = scaleBoundingBox(
                  box,
                  activePage.width,
                  activePage.height,
                  displaySize.width,
                  displaySize.height
                );
                if (!scaled) return null;

                const isHighlighted =
                  selectedFindingIndex === findingIndex ||
                  (highlightedBox &&
                    highlightedBox.page === box.page &&
                    highlightedBox.x === box.x &&
                    highlightedBox.y === box.y);

                const isSuspicious = finding.status === "suspicious";

                return (
                  <button
                    key={`overlay-${findingIndex}-${boxIndex}`}
                    type="button"
                    data-testid="overlay-box"
                    onClick={() => onSelectBox(findingIndex, box)}
                    title={`${formatDetectorLabel(finding.name)}: ${finding.evidence}`}
                    style={{
                      left: `${scaled.left}px`,
                      top: `${scaled.top}px`,
                      width: `${scaled.width}px`,
                      height: `${scaled.height}px`,
                    }}
                    className={`absolute border-2 rounded-sm transition-all focus:outline-none ${
                      isHighlighted
                        ? "border-sky-600 bg-sky-500/20 ring-2 ring-sky-400 z-20"
                        : isSuspicious
                        ? "border-red-600 bg-red-500/15 hover:bg-red-500/25 z-10"
                        : "border-amber-500 bg-amber-400/15 hover:bg-amber-400/25 z-10"
                    }`}
                  >
                    <span
                      className={`absolute -top-5 left-0 px-1.5 py-0.5 rounded text-[10px] font-semibold whitespace-nowrap text-white shadow ${
                        isHighlighted
                          ? "bg-sky-700"
                          : isSuspicious
                          ? "bg-red-600"
                          : "bg-amber-600"
                      }`}
                    >
                      {formatDetectorLabel(finding.name)}
                    </span>
                  </button>
                );
              })}

            {/* Highlighted field location if user clicked a field chip */}
            {showOverlays &&
              highlightedBox &&
              highlightedBox.isFieldLocation &&
              highlightedBox.page === pageIndex &&
              displaySize.width > 0 &&
              (() => {
                const scaled = scaleBoundingBox(
                  highlightedBox,
                  activePage.width,
                  activePage.height,
                  displaySize.width,
                  displaySize.height
                );
                if (!scaled) return null;
                return (
                  <div
                    style={{
                      left: `${scaled.left}px`,
                      top: `${scaled.top}px`,
                      width: `${scaled.width}px`,
                      height: `${scaled.height}px`,
                    }}
                    className="absolute border-2 border-sky-600 bg-sky-400/20 rounded-sm pointer-events-none z-20"
                  />
                );
              })()}
          </div>
        </div>
      )}
    </section>
  );
}
