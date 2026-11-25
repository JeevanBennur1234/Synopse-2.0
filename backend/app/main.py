from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pathlib import Path
from uuid import uuid4
import sqlite3, json, os, logging
from pydantic import BaseModel, Field
from typing import Literal
from app.schemas import DetectorResult
from app.preprocessing.document import validate, process
from app.preprocessing.fields import locate
from app.preprocessing.tables import extract_tables
from app.pipeline.orchestrator import execute
from app.scoring.risk import calculate
from app.adapters.gst_registry import check_registry, RegistryCheck
from app.explainability import explain, Explanation

ROOT = Path(os.environ.get("KAVACH_DATA", str(Path(__file__).resolve().parents[1] / "uploads")))
ROOT.mkdir(parents=True, exist_ok=True)
DB = ROOT / "jobs.sqlite"
MAX_BYTES = 15 * 1024 * 1024
app = FastAPI(title="Kavach", version="0.1.1")

class HealthResponse(BaseModel):
    status: Literal["ok"]

class JobAccepted(BaseModel):
    job_id: str
    status: Literal["queued"]

class ErrorResponse(BaseModel):
    detail: str

class Word(BaseModel):
    text: str
    page: int
    x: int
    y: int
    w: int
    h: int
    confidence: float | None = None

class PageResult(BaseModel):
    page: int
    width: int
    height: int
    text: str
    words: list[Word]
    method: Literal["native_pdf", "ocr"]
    preview_url: str

class EngineRun(BaseModel):
    engine: str
    status: Literal['completed', 'inconclusive', 'error', 'unavailable', 'not_applicable']
    finding_count: int

class JobResult(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    risk_score: float | None = None
    risk_level: Literal["low", "medium", "high", "inconclusive"]
    coverage: float
    findings: list[DetectorResult]
    pages: list[PageResult]
    fields: dict[str, list[str]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    engine_runs: list[EngineRun] = Field(default_factory=list)
    field_locations: dict[str, list[dict]] = Field(default_factory=dict)
    registry_checks: list[RegistryCheck] = Field(default_factory=list)
    explanation: Explanation | None = None


def connect():
    return sqlite3.connect(DB)

with connect() as db:
    db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, result TEXT NOT NULL)")

def save(job):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?)", (job["job_id"], json.dumps(job)))

def load(job_id):
    with connect() as db:
        row = db.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return json.loads(row[0])

def run(job, source):
    job["status"] = "running"
    save(job)
    try:
        pages, fields, warnings = process(source)
        for page in pages:
            page["preview_url"] = f'/result/{job["job_id"]}/pages/{page["page"]}'
        locations = locate(pages, fields)
        context = dict(fields, _pages=pages, _field_locations=locations)
        tables, table_warnings = extract_tables(pages)
        context.update(tables)
        warnings.extend(table_warnings)
        findings, runs, detector_warnings = execute(source, pages, context)
        risk = calculate(runs)
        job.update(**risk)
        job.update(status="completed", pages=pages, fields=fields, field_locations=locations, findings=[f.model_dump() for f in findings], engine_runs=runs, warnings=warnings + detector_warnings + (["Insufficient conclusive evidence for overall risk."] if risk["risk_score"] is None else []))
        try:
            job["registry_checks"] = [r.model_dump() for r in check_registry(fields, locations)]
        except Exception:
            logging.exception("Mock registry lookup failed")
            job["warnings"].append("Mock registry lookup unavailable.")
        try:
            job["explanation"] = explain(risk, findings, runs, job["warnings"]).model_dump()
        except Exception:
            logging.exception("Explanation generation failed")
            job["warnings"].append("Explanation unavailable.")
    except Exception:
        logging.exception("Processing failed for job %s", job["job_id"])
        job.update(status="failed", warnings=["Document processing failed."])
    save(job)

@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}

@app.post("/analyze", status_code=202, response_model=JobAccepted, responses={413: {"model": ErrorResponse}, 422: {"description": "Invalid upload"}})
async def analyze(background: BackgroundTasks, file: UploadFile = File(...)):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large")
    try:
        suffix = validate(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    job_id = uuid4().hex
    folder = ROOT / job_id
    folder.mkdir()
    source = folder / ("original" + suffix)
    source.write_bytes(data)
    job = dict(job_id=job_id, status="queued", risk_score=None, risk_level="inconclusive", coverage=0, findings=[], pages=[])
    save(job)
    background.add_task(run, job, source)
    return {"job_id": job_id, "status": "queued"}

@app.get("/result/{job_id}", response_model=JobResult, responses={404: {"model": ErrorResponse}})
def result(job_id: str):
    return load(job_id)

@app.get("/result/{job_id}/pages/{page}", response_class=FileResponse, responses={200: {"content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}}, 404: {"model": ErrorResponse}})
def preview(job_id: str, page: int):
    job = load(job_id)
    if not any(p["page"] == page for p in job["pages"]):
        raise HTTPException(404, "Page not found")
    return FileResponse(ROOT / job["job_id"] / f"page-{page}.png", media_type="image/png")
