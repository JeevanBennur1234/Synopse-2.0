from app.pipeline.orchestrator import execute, Engine
from app.schemas import DetectorResult

class Good:
    def analyze(self, source, pages, fields):
        assert pages[0].name == "page-0.png"
        fields.clear()
        return [DetectorResult(name="test",score=.8,confidence=.9,status="suspicious",evidence="Synthetic test only")]

class Bad:
    def analyze(self,*args):
        raise RuntimeError("test failure")

class Invalid:
    def analyze(self,*args):
        return [dict(name="invalid",score=2,confidence=1,status="passed",evidence="test")]

class Outside:
    def analyze(self,*args):
        return [dict(name="outside",score=.5,confidence=1,status="suspicious",evidence="test",boxes=[dict(page=0,x=99,y=0,w=2,h=1)])]

def test_pipeline(tmp_path):
    fields={"total":["100"]}
    findings,runs,warnings=execute(tmp_path/"original.pdf",[dict(page=0,width=100,height=100)],fields,[Engine("bad",Bad()),Engine("good",Good()),Engine("invalid",Invalid()),Engine("outside",Outside()),Engine("missing")])
    assert [r["status"] for r in runs]==["error","completed","error","error","unavailable"]
    assert len(findings)==1
    assert fields=={"total":["100"]}
    assert len(warnings)==4

def test_unregistered(tmp_path):
    findings,runs,warnings=execute(tmp_path/"original.pdf",[],{})
    assert not findings
    assert len(runs)==3
    assert all(r["status"]=="unavailable" for r in runs)
