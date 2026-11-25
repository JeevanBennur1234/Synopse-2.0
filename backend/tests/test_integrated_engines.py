from app.preprocessing.fields import extract, locate
from app.preprocessing.tables import extract_tables
from app.scoring.risk import calculate
from fastapi.testclient import TestClient
from app.main import app
import fitz

def test_extended_fields():
    f=extract("Invoice date: 25/11/2026\nDue date: 30/11/2026\nGST rate: 18%\nUTGST: 90\nPlace of supply: Karnataka")
    assert f["invoice_date"]==["25/11/2026"]
    assert f["due_date"]==["30/11/2026"]
    assert f["tax_rate"]==["18"]
    assert f["utgst"]==["90"]

def test_tables():
    pages=[dict(page=0,method="native_pdf",text="Description Qty Unit Price Amount\nWidget 2 50 100\nSubtotal 100")]
    out,w=extract_tables(pages)
    assert out["_line_items"][0]["amount"]=="100"
    pages=[dict(page=0,method="native_pdf",text="Date Description Debit Credit Balance\n25/11/2026 Deposit - 100 200\nClosing balance 200")]
    out,w=extract_tables(pages)
    assert out["_bank_transactions"][0]["debit"]=="0"
    pages[0]["method"]="ocr"
    assert "_bank_transactions" not in extract_tables(pages)[0]

def test_applicable_coverage():
    runs=[dict(engine=k,status="completed",findings=[dict(status="passed",score=0,confidence=1)]) for k in ("visual","consistency")]
    runs.append(dict(engine="file_forensics",status="not_applicable",findings=[dict(status="not_applicable")]))
    assert calculate(runs)==dict(risk_score=0,risk_level="low",coverage=1)
    runs[-1]["status"]="error"
    assert calculate(runs)["risk_level"]=="inconclusive"

def test_real_engines():
    doc=fitz.open()
    p=doc.new_page()
    p.insert_text((40,40),"SAMPLE / TEST ONLY\nInvoice no: TEST-2\nSubtotal: 1000\nCGST: 90\nSGST: 90\nGrand total: 1500")
    data=doc.tobytes()
    doc.close()
    c=TestClient(app)
    r=c.post("/analyze",files={"file":("test.pdf",data)})
    j=c.get("/result/"+r.json()["job_id"]).json()
    assert j["status"]=="completed"
    assert len(j["engine_runs"])==3
    assert all(r["status"] not in ("error","unavailable") for r in j["engine_runs"])
    assert any(f["name"]=="invoice_arithmetic_consistency" and f["status"]=="suspicious" and f["boxes"] for f in j["findings"])
    print("LIVE API:",j["risk_score"],j["risk_level"],j["coverage"],j["engine_runs"])

