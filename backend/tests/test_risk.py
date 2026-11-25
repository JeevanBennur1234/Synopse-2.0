from app.scoring.risk import calculate, evaluate
from app.explainability import explain
from app.schemas import DetectorResult

def run(name, score, confidence=1, status="suspicious"):
    return dict(engine=name,status="completed",findings=[dict(score=score,confidence=confidence,status=status)])

def test_full():
    assert calculate([run("visual",.8),run("file_forensics",.4),run("consistency",.9)]) == dict(risk_score=77.0,risk_level="high",coverage=1.0)

def test_missing():
    assert calculate([])["risk_score"] is None
    assert calculate([run("consistency",1)])["risk_score"] is None

def test_partial():
    assert calculate([run("visual",.8),run("consistency",.9)])["risk_score"] == 86.25
    assert calculate([run("visual",0),run("consistency",0)])["risk_level"] == "inconclusive"

def test_uncertain():
    assert calculate([run("visual",1,.1),run("consistency",1),run("file_forensics",1,status="error")])["coverage"] == .5

def test_low():
    assert calculate([run(k,0,status="passed") for k in ("visual","file_forensics","consistency")])["risk_level"] == "low"

def test_single_strong_finding_floors_at_medium():
    runs = [
        dict(engine="visual", status="completed", findings=[dict(name="copy_move", score=0.65, confidence=0.75, status="suspicious")]),
        dict(engine="file_forensics", status="not_applicable", findings=[dict(name="file_forensics", score=0.0, confidence=0.0, status="not_applicable")]),
        dict(engine="consistency", status="completed", findings=[dict(name="invoice_arithmetic_consistency", score=0.0, confidence=0.9, status="passed")]),
    ]
    risk, meta = evaluate(runs)
    assert risk["risk_level"] == "medium"
    assert risk["risk_score"] < 35
    assert meta["floor_applied"] is True
    annotated = [f for r in meta["annotated_runs"] for f in r["findings"]]
    cm = next(f for f in annotated if f["name"] == "copy_move")
    assert cm["severity"] == "strong"
    assert cm["corroborated"] is False
    exp = explain(
        risk,
        [DetectorResult(**f, evidence="duplicated seal") for f in annotated],
        runs,
        [],
        floor_applied=meta["floor_applied"],
        other_checks_clean=meta["other_checks_clean"],
    )
    assert any("one strong signal found; other checks clean" in r.evidence.lower() for r in exp.reasons)

def test_two_independent_strong_findings_floor_at_high():
    runs = [
        dict(engine="visual", status="completed", findings=[dict(name="copy_move", score=0.45, confidence=0.75, status="suspicious")]),
        dict(engine="file_forensics", status="completed", findings=[dict(name="pdf_structural_integrity", score=0.50, confidence=0.85, status="suspicious")]),
        dict(engine="consistency", status="completed", findings=[dict(name="gstin_validation", score=0.0, confidence=0.9, status="passed")]),
    ]
    risk, meta = evaluate(runs)
    assert risk["risk_score"] < 70
    assert risk["risk_level"] == "high"
    assert meta["floor_applied"] is True
    annotated = [f for r in meta["annotated_runs"] for f in r["findings"]]
    assert all(f["severity"] == "strong" and f["corroborated"] is True for f in annotated if f["status"] == "suspicious")

def test_ela_alone_never_produces_high():
    runs = [
        dict(engine="visual", status="completed", findings=[dict(name="ela", score=0.95, confidence=0.90, status="suspicious")]),
        dict(engine="file_forensics", status="not_applicable", findings=[dict(name="file_forensics", score=0.0, confidence=0.0, status="not_applicable")]),
        dict(engine="consistency", status="not_applicable", findings=[dict(name="consistency", score=0.0, confidence=0.0, status="not_applicable")]),
    ]
    risk, meta = evaluate(runs)
    assert risk["risk_level"] != "high"
    assert risk["risk_level"] == "medium"
    ela_f = meta["annotated_runs"][0]["findings"][0]
    assert ela_f["severity"] == "suspicious"

def test_mixed_inconclusive_needs_review_not_low():
    runs = [
        dict(engine="visual", status="completed", findings=[dict(name="copy_move", score=0.0, confidence=0.7, status="passed")]),
        dict(engine="file_forensics", status="inconclusive", findings=[dict(name="pdf_metadata_integrity", score=0.0, confidence=0.25, status="inconclusive")]),
        dict(engine="consistency", status="completed", findings=[dict(name="gstin_validation", score=0.0, confidence=0.9, status="passed")]),
    ]
    risk, meta = evaluate(runs)
    assert risk["risk_level"] == "inconclusive"
    assert risk["risk_score"] is None
    annotated = [f for r in meta["annotated_runs"] for f in r["findings"]]
    exp = explain(risk, [DetectorResult(**f, evidence="check") for f in annotated], runs, [])
    assert "needs review" in exp.summary.lower()
    assert "needs review" in exp.recommendation.lower()
    assert any("not checked" in lim.lower() for lim in exp.limitations)
