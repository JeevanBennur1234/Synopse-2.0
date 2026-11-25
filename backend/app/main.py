from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Response
from fastapi.responses import FileResponse
from pathlib import Path
from uuid import uuid4
import asyncio, sqlite3, json, os, logging, re, shutil, subprocess, sys, threading, time
from pydantic import BaseModel, Field
from typing import Literal
from app.schemas import DetectorResult
from app.preprocessing.document import validate
from app.adapters.gst_registry import RegistryCheck
from app.explainability import Explanation

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("KAVACH_DATA", str(BACKEND_DIR / "uploads")))
ROOT.mkdir(parents=True, exist_ok=True)
DB = ROOT / "jobs.sqlite"
MAX_BYTES = 15 * 1024 * 1024
MAX_CONCURRENT_JOBS = max(1, int(os.environ.get("KAVACH_MAX_CONCURRENT_JOBS", "2")))
JOB_TIMEOUT_SECONDS = max(1, int(os.environ.get("KAVACH_JOB_TIMEOUT_SECONDS", "120")))
JOB_TTL_MINUTES = max(0.01, float(os.environ.get("KAVACH_JOB_TTL_MINUTES", "60")))
VALID_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
ACTIVE_JOBS: set[str] = set()
ACTIVE_JOBS_LOCK = threading.Lock()
app = FastAPI(title="Kavach", version="0.1.1")

class HealthResponse(BaseModel):
    status: Literal["ok"]

class JobAccepted(BaseModel):
    job_id: str
    status: Literal["queued"]

class ErrorResponse(BaseModel):
    detail: str

class JobDeleteResponse(BaseModel):
    job_id: str
    deleted: bool

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
    review_required: bool = False
    insufficient_core_evidence: bool = False
    check_status_counts: dict[str, int] = Field(default_factory=dict)
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
    return sqlite3.connect(DB, timeout=10.0)


def _ensure_valid_job_id(job_id: str) -> None:
    if not VALID_JOB_ID_RE.fullmatch(job_id):
        raise HTTPException(404, "Job not found")


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            check=False,
        )
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=5)
    except Exception:
        pass


def cleanup_expired_jobs(now: float | None = None) -> int:
    """Remove expired jobs' files, page renders, and DB rows."""
    current_time = now if now is not None else time.time()
    cutoff = current_time - (JOB_TTL_MINUTES * 60.0)
    with ACTIVE_JOBS_LOCK:
        active_snapshot = set(ACTIVE_JOBS)

    with connect() as db:
        rows = db.execute("SELECT id, result FROM jobs").fetchall()

    expired_ids: list[str] = []
    for jid, raw in rows:
        if jid in active_snapshot or not VALID_JOB_ID_RE.fullmatch(jid):
            continue
        created_at: float | None = None
        try:
            payload = json.loads(raw)
            if isinstance(payload.get("created_at"), (int, float)):
                created_at = float(payload["created_at"])
        except Exception:
            created_at = None
        if created_at is None:
            folder = ROOT / jid
            created_at = folder.stat().st_mtime if folder.exists() else 0.0
        if created_at < cutoff:
            expired_ids.append(jid)

    if expired_ids:
        with connect() as db:
            db.executemany("DELETE FROM jobs WHERE id=?", [(jid,) for jid in expired_ids])
        for jid in expired_ids:
            shutil.rmtree(ROOT / jid, ignore_errors=True)

    return len(expired_ids)


with connect() as db:
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, result TEXT NOT NULL)")


def save(job):
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO jobs VALUES (?, ?)", (job["job_id"], json.dumps(job)))


def load(job_id):
    _ensure_valid_job_id(job_id)
    with connect() as db:
        row = db.execute("SELECT result FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return json.loads(row[0])


def run(job, source):
    job_id = job["job_id"]
    output_path = ROOT / job_id / ".worker_result.json"
    env = os.environ.copy()
    env["KAVACH_DATA"] = str(ROOT)
    try:
        job["status"] = "running"
        save(job)
        proc = subprocess.Popen(
            [sys.executable, "-m", "app.job_worker", job_id, str(source), str(output_path)],
            cwd=str(BACKEND_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            _, stderr_bytes = proc.communicate(timeout=JOB_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc)
            output_path.unlink(missing_ok=True)
            logging.error("Processing timed out for job %s after %ss", job_id, JOB_TIMEOUT_SECONDS)
            job.update(status="failed", warnings=["Document processing timed out."])
            save(job)
            return

        if proc.returncode == 0 and output_path.exists():
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            output_path.unlink(missing_ok=True)
            job.update(payload)
        else:
            stderr_text = (stderr_bytes or b"").decode("utf-8", errors="replace").strip()
            logging.error("Worker failed for job %s (rc=%s): %s", job_id, proc.returncode, stderr_text)
            if output_path.exists():
                try:
                    payload = json.loads(output_path.read_text(encoding="utf-8"))
                    job.update(payload)
                except Exception:
                    job.update(status="failed", warnings=["Document processing failed."])
                output_path.unlink(missing_ok=True)
            else:
                job.update(status="failed", warnings=["Document processing failed."])
    except Exception:
        logging.exception("Processing failed for job %s", job_id)
        job.update(status="failed", warnings=["Document processing failed."])
    finally:
        with ACTIVE_JOBS_LOCK:
            ACTIVE_JOBS.discard(job_id)
    save(job)


@app.get("/health", response_model=HealthResponse)
def health():
    return {"status": "ok"}


@app.post(
    "/analyze",
    status_code=202,
    response_model=JobAccepted,
    responses={
        413: {"model": ErrorResponse},
        422: {"description": "Invalid upload"},
        503: {"model": ErrorResponse},
    },
)
async def analyze(background: BackgroundTasks, file: UploadFile = File(...)):
    cleanup_expired_jobs()
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large")
    try:
        suffix = await asyncio.to_thread(validate, data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))

    job_id = uuid4().hex
    with ACTIVE_JOBS_LOCK:
        if len(ACTIVE_JOBS) >= MAX_CONCURRENT_JOBS:
            raise HTTPException(503, "Server busy; maximum concurrent analysis jobs reached")
        ACTIVE_JOBS.add(job_id)

    try:
        folder = ROOT / job_id
        folder.mkdir()
        source = folder / ("original" + suffix)
        source.write_bytes(data)
        job = dict(
            job_id=job_id,
            status="queued",
            created_at=time.time(),
            risk_score=None,
            risk_level="inconclusive",
            coverage=0,
            findings=[],
            pages=[],
        )
        save(job)
    except Exception:
        with ACTIVE_JOBS_LOCK:
            ACTIVE_JOBS.discard(job_id)
        shutil.rmtree(ROOT / job_id, ignore_errors=True)
        raise

    background.add_task(run, job, source)
    return {"job_id": job_id, "status": "queued"}


@app.get("/result/{job_id}", response_model=JobResult, responses={404: {"model": ErrorResponse}})
def result(job_id: str, response: Response):
    cleanup_expired_jobs()
    response.headers["Cache-Control"] = "no-store"
    return load(job_id)


@app.get(
    "/result/{job_id}/pages/{page}",
    response_class=FileResponse,
    responses={
        200: {"content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}},
        404: {"model": ErrorResponse},
    },
)
def preview(job_id: str, page: int):
    cleanup_expired_jobs()
    job = load(job_id)
    if not any(p["page"] == page for p in job["pages"]):
        raise HTTPException(404, "Page not found")
    return FileResponse(
        ROOT / job["job_id"] / f"page-{page}.png",
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.delete(
    "/jobs/{job_id}",
    response_model=JobDeleteResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def delete_job(job_id: str, response: Response):
    _ensure_valid_job_id(job_id)
    response.headers["Cache-Control"] = "no-store"
    with ACTIVE_JOBS_LOCK:
        if job_id in ACTIVE_JOBS:
            raise HTTPException(409, "Cannot delete an active analysis job")
    with connect() as db:
        cur = db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        deleted_count = cur.rowcount
    if deleted_count == 0:
        raise HTTPException(404, "Job not found")
    shutil.rmtree(ROOT / job_id, ignore_errors=True)
    return {"job_id": job_id, "deleted": True}
