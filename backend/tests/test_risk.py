from app.scoring.risk import calculate

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
