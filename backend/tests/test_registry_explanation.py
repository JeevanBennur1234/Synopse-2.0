from app.adapters.gst_registry import check_registry, FIXTURE_ID
from app.explainability import explain
from app.schemas import DetectorResult
from app.main import app
from fastapi.testclient import TestClient
import fitz

def test_mock_registry():
    assert check_registry({}, {}) == []
    r=check_registry({"gstin":[FIXTURE_ID]}, {})[0]
    assert r.status=="mock_match" and not r.authoritative
    assert check_registry({"gstin":["INVALID"]}, {})[0].status=="invalid_format"
    assert check_registry({"gstin":[FIXTURE_ID]}, {"gstin":[{"value":FIXTURE_ID,"confidence":.3}]})[0].status=="uncertain_ocr"
    from app.detectors.consistency.gstin import compute_gstin_checksum
    prefix="29ZZZZZ0000Z2Z"
    unknown=prefix+compute_gstin_checksum(prefix)
    assert check_registry({"gstin":[unknown]}, {})[0].status=="not_in_fixture"

def test_explanation():
    f=DetectorResult(name="test",status="suspicious",score=.8,confidence=.9,evidence="Actual evidence")
    e=explain(dict(risk_level="inconclusive",risk_score=None,coverage=.3),[f],[],[])
    assert "insufficient" in e.summary and e.reasons[0].evidence==f.evidence
    assert e.reasons[0].pages==[]
    assert "not a probability" in e.limitations[0]

def test_api_additive():
    doc=fitz.open()
    p=doc.new_page()
    p.insert_text((40,40),f"SAMPLE / TEST ONLY\nGSTIN: {FIXTURE_ID}\nSubtotal: 1000\nCGST: 90\nSGST: 90\nGrand total: 1500")
    data=doc.tobytes()
    doc.close()
    c=TestClient(app)
    r=c.post("/analyze",files={"file":("sample.pdf",data)})
    j=c.get("/result/"+r.json()["job_id"]).json()
    assert j["status"]=="completed"
    assert j["registry_checks"][0]["status"]=="mock_match"
    assert j["registry_checks"][0]["authoritative"] is False
    assert any(r["detector"]=="invoice_arithmetic_consistency" for r in j["explanation"]["reasons"])
    assert all(r["evidence"] in [f["evidence"] for f in j["findings"]] for r in j["explanation"]["reasons"])
    print("API:",j["risk_score"],j["registry_checks"],j["explanation"]["summary"])

