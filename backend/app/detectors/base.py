from pathlib import Path
from typing import Protocol, Any
from app.schemas import DetectorResult

class Detector(Protocol):
    def analyze(self, source: Path, pages: list[Path], fields: dict[str, Any]) -> list[DetectorResult]: ...
