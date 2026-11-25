import os, tempfile
os.environ["KAVACH_DATA"] = tempfile.mkdtemp()
from fastapi.testclient import TestClient
from app.main import app
import fitz

client = TestClient(app)

def test_health():
    assert client.get("/health").json()["status"] == "ok"

def test_invalid():
    assert client.post("/analyze",files={"file":("bad.pdf",b"bad")}).status_code == 422

def test_pdf():
    doc=fitz.open()
    page=doc.new_page()
    page.insert_text((50,50),"SAMPLE/TEST\nGrand total: 11800\nInvoice no: TEST-1")
    data=doc.tobytes()
    doc.close()
    response=client.post("/analyze",files={"file":("sample.pdf",data)})
    assert response.status_code == 202
    job=client.get("/result/"+response.json()["job_id"]).json()
    assert job["status"] == "completed"
    assert job["fields"]["total"] == ["11800"]
    assert job["risk_score"] is None
    assert client.get(job["pages"][0]["preview_url"]).status_code == 200

def test_missing():
    assert client.get("/result/missing").status_code == 404
