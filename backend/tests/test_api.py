import os, tempfile
os.environ["KAVACH_DATA"] = tempfile.mkdtemp()
from fastapi.testclient import TestClient
from app.main import app
import time
import fitz
import app.main as main_mod

client = TestClient(app)


def _sample_pdf_bytes(text: str = "SAMPLE/TEST\nGrand total: 11800\nInvoice no: TEST-1") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_health():
    assert client.get("/health").json()["status"] == "ok"


def test_invalid():
    assert client.post("/analyze", files={"file": ("bad.pdf", b"bad")}).status_code == 422


def test_pdf_and_cache_control_headers():
    data = _sample_pdf_bytes()
    response = client.post("/analyze", files={"file": ("sample.pdf", data)})
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    res = client.get("/result/" + job_id)
    assert res.status_code == 200
    assert res.headers.get("cache-control") == "no-store"

    job = res.json()
    assert job["status"] == "completed"
    assert job["fields"]["total"] == ["11800"]
    assert job["risk_score"] is None

    page_res = client.get(job["pages"][0]["preview_url"])
    assert page_res.status_code == 200
    assert page_res.headers.get("cache-control") == "no-store"


def test_missing():
    assert client.get("/result/missing").status_code == 404


def test_delete_job_lifecycle():
    data = _sample_pdf_bytes()
    response = client.post("/analyze", files={"file": ("del.pdf", data)})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    folder = main_mod.ROOT / job_id
    assert folder.exists()

    del_res = client.delete(f"/jobs/{job_id}")
    assert del_res.status_code == 200
    assert del_res.json() == {"job_id": job_id, "deleted": True}
    assert del_res.headers.get("cache-control") == "no-store"
    assert not folder.exists()
    assert client.get(f"/result/{job_id}").status_code == 404
    assert client.delete(f"/jobs/{job_id}").status_code == 404


def test_delete_active_job_rejected():
    active_id = "a" * 32
    with main_mod.ACTIVE_JOBS_LOCK:
        main_mod.ACTIVE_JOBS.add(active_id)
    try:
        res = client.delete(f"/jobs/{active_id}")
        assert res.status_code == 409
    finally:
        with main_mod.ACTIVE_JOBS_LOCK:
            main_mod.ACTIVE_JOBS.discard(active_id)


def test_concurrency_limit_and_slot_release(monkeypatch):
    monkeypatch.setattr(main_mod, "MAX_CONCURRENT_JOBS", 1)
    busy_id = "b" * 32
    with main_mod.ACTIVE_JOBS_LOCK:
        main_mod.ACTIVE_JOBS.add(busy_id)
    try:
        res_busy = client.post("/analyze", files={"file": ("busy.pdf", _sample_pdf_bytes())})
        assert res_busy.status_code == 503
    finally:
        with main_mod.ACTIVE_JOBS_LOCK:
            main_mod.ACTIVE_JOBS.discard(busy_id)

    # Slot released; subsequent request succeeds and releases its own slot upon completion
    res_ok = client.post("/analyze", files={"file": ("ok.pdf", _sample_pdf_bytes())})
    assert res_ok.status_code == 202
    with main_mod.ACTIVE_JOBS_LOCK:
        assert len(main_mod.ACTIVE_JOBS) == 0


def test_ttl_cleanup_removes_expired_files_and_rows(monkeypatch):
    monkeypatch.setattr(main_mod, "JOB_TTL_MINUTES", 5.0)
    res = client.post("/analyze", files={"file": ("ttl.pdf", _sample_pdf_bytes())})
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    folder = main_mod.ROOT / job_id
    assert folder.exists()

    removed_now = main_mod.cleanup_expired_jobs(now=time.time())
    assert removed_now == 0
    assert client.get(f"/result/{job_id}").status_code == 200

    removed_later = main_mod.cleanup_expired_jobs(now=time.time() + 600.0)
    assert removed_later >= 1
    assert not folder.exists()
    assert client.get(f"/result/{job_id}").status_code == 404


def test_job_processing_timeout(monkeypatch):
    import subprocess as sp

    monkeypatch.setattr(main_mod, "JOB_TIMEOUT_SECONDS", 1)
    orig_popen = sp.Popen

    def slow_popen(*args, **kwargs):
        return orig_popen(
            [main_mod.sys.executable, "-c", "import time; time.sleep(5)"],
            stdout=sp.PIPE,
            stderr=sp.PIPE,
        )

    monkeypatch.setattr(main_mod.subprocess, "Popen", slow_popen)
    res = client.post("/analyze", files={"file": ("slow.pdf", _sample_pdf_bytes())})
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    job = client.get(f"/result/{job_id}").json()
    assert job["status"] == "failed"
    assert "Document processing timed out." in job["warnings"]
    with main_mod.ACTIVE_JOBS_LOCK:
        assert job_id not in main_mod.ACTIVE_JOBS
