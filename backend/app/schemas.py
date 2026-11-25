from typing import Literal
from pydantic import BaseModel, Field

class BoundingBox(BaseModel):
    page: int = Field(ge=0)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(gt=0)
    h: int = Field(gt=0)

class DetectorResult(BaseModel):
    name: str
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    status: Literal["passed", "suspicious", "inconclusive", "not_applicable", "error"]
    evidence: str
    boxes: list[BoundingBox] = Field(default_factory=list)
    severity: Literal["info", "suspicious", "strong"] = "info"
    corroborated: bool = False
