from pathlib import Path
from threading import Barrier, Event

from app.detectors.visual.pipeline import VisualForensicsDetector
from app.schemas import DetectorResult


class Probe:
    def __init__(self, name, action):
        self.name = name
        self.action = action

    def analyze(self, source, pages, fields):
        self.action()
        return [DetectorResult(
            name=self.name, score=0, confidence=1, status="passed", evidence="probe",
        )]


def test_visual_detectors_run_in_parallel_and_keep_output_order():
    barrier = Barrier(2, timeout=1)
    pipeline = VisualForensicsDetector([Probe("first", barrier.wait), Probe("second", barrier.wait)])
    results = pipeline.analyze(Path("sample.jpg"), [], {})
    assert [(r.name, r.status) for r in results] == [("first", "passed"), ("second", "passed")]


def test_visual_detector_timeout_preserves_other_evidence(monkeypatch):
    monkeypatch.setenv("KAVACH_DETECTOR_TIMEOUT_SECONDS", "0.2")
    release = Event()
    pipeline = VisualForensicsDetector([
        Probe("slow", release.wait), Probe("fast", lambda: None),
    ])
    try:
        results = pipeline.analyze(Path("sample.jpg"), [], {})
        assert [(r.name, r.status) for r in results] == [("slow", "error"), ("fast", "passed")]
        assert "exceeded 0.2s" in results[0].evidence
    finally:
        release.set()
