"""Unified entry point for Kavach visual and image metadata forensic detectors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.detectors.base import Detector
from app.detectors.image_metadata.analyzer import ImageMetadataDetector
from app.detectors.visual.copy_move import CopyMoveDetector
from app.detectors.visual.ela import ELADetector
from app.detectors.visual.noise import NoiseInconsistencyDetector
from app.detectors.visual.typography import TypographyDetector
from app.schemas import DetectorResult


class VisualForensicsDetector:
    """Runs all visual and image-metadata detectors behind the shared Detector protocol."""

    def __init__(self, detectors: list[Detector] | None = None) -> None:
        self._detectors: list[Detector] = (
            list(detectors)
            if detectors is not None
            else [
                ELADetector(),
                CopyMoveDetector(),
                NoiseInconsistencyDetector(),
                ImageMetadataDetector(),
                TypographyDetector(),
            ]
        )

    def analyze(
        self, source: Path, pages: list[Path], fields: dict[str, Any]
    ) -> list[DetectorResult]:
        """Execute all visual detectors and isolate any per-detector failures."""
        results: list[DetectorResult] = []
        for detector in self._detectors:
            det_name = getattr(detector, "name", detector.__class__.__name__)
            try:
                sub_results = detector.analyze(source, pages, fields)
                results.extend(sub_results)
            except Exception as exc:
                results.append(
                    DetectorResult(
                        name=det_name,
                        score=0.0,
                        confidence=0.0,
                        status="error",
                        evidence=f"Detector '{det_name}' raised an unexpected error: {exc}",
                        boxes=[],
                    )
                )
        return results


def analyze(
    source: Path, pages: list[Path], fields: dict[str, Any]
) -> list[DetectorResult]:
    """Documented entry point for Member 1's orchestrator.

    Args:
        source: Path to the original uploaded file (PDF, PNG, or JPEG).
        pages: List of paths to rendered page images (zero-based page order).
        fields: Extracted document fields dictionary.

    Returns:
        List of DetectorResult objects from ELA, copy-move, noise, and image metadata.
    """
    return VisualForensicsDetector().analyze(source, pages, fields)
