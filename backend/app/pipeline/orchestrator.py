from dataclasses import dataclass
from pathlib import Path
from copy import deepcopy
import logging
from app.schemas import DetectorResult
from app.detectors.base import Detector

@dataclass(frozen=True)
class Engine:
    name: str
    detector: Detector | None = None

# Explicit registration only. Never execute test detectors in production.
ENGINES = tuple(Engine(name) for name in ("visual", "file_forensics", "consistency"))

def execute(source: Path, pages: list[dict], fields: dict, engines=None):
    findings, runs, warnings = [], [], []
    paths = [source.parent / f"page-{p['page']}.png" for p in pages]
    dimensions = {p["page"]: (p["width"], p["height"]) for p in pages}
    for engine in ENGINES if engines is None else engines:
        if engine.detector is None:
            runs.append(dict(engine=engine.name, status="unavailable", finding_count=0))
            warnings.append(f"{engine.name}: detector not registered")
            continue
        try:
            raw = engine.detector.analyze(source, list(paths), deepcopy(fields))
            if not isinstance(raw, list):
                raise TypeError("Detector must return a list")
            results = [DetectorResult.model_validate(r.model_dump() if isinstance(r, DetectorResult) else r) for r in raw]
            for result in results:
                for box in result.boxes:
                    size = dimensions.get(box.page)
                    if size is None or box.x+box.w > size[0] or box.y+box.h > size[1]:
                        raise ValueError("Bounding box outside rendered page")
            findings.extend(results)
            status = "completed" if any(r.status in ("passed","suspicious") for r in results) else "inconclusive"
            runs.append(dict(engine=engine.name,status=status,finding_count=len(results), findings=[r.model_dump() for r in results]))
            if status == "inconclusive":
                warnings.append(f"{engine.name}: no conclusive findings")
        except Exception:
            logging.exception("Detector failed: %s", engine.name)
            runs.append(dict(engine=engine.name,status="error",finding_count=0))
            warnings.append(f"{engine.name}: detector execution failed")
    return findings, runs, warnings
