"""Deterministic evidence summaries; no external model or invented evidence."""
from pydantic import BaseModel, Field
from typing import Literal

class Reason(BaseModel):
    detector: str
    evidence: str
    confidence: float
    pages: list[int]

class Explanation(BaseModel):
    summary: str
    reasons: list[Reason] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommendation: str
    method: Literal["deterministic"] = "deterministic"

def explain(risk, findings, runs, warnings):
    suspicious = sorted((f for f in findings if f.status == "suspicious"), key=lambda f: f.score*f.confidence, reverse=True)
    reasons = [Reason(detector=f.name,evidence=f.evidence,confidence=f.confidence,pages=sorted({b.page for b in f.boxes})) for f in suspicious]
    level = risk["risk_level"]
    score = risk["risk_score"]
    if score is None:
        summary = "Available evidence is insufficient for an overall risk rating."
    else:
        summary = f"Overall heuristic risk is {level} ({score:g}/100)."
    summary += f" {len(reasons)} suspicious finding(s); engine evidence coverage {risk['coverage']:.0%}."
    limits = ["Risk is a heuristic, not a probability of fraud or proof of authenticity.", "GST registry lookup is a synthetic demonstration, not government verification."]
    for status in ("inconclusive","not_applicable","error"):
        names = sorted({f.name for f in findings if f.status == status})
        if names:
            limits.append(f"Checks marked {status}: " + ", ".join(names))
    for run in runs:
        if run["status"] in ("unavailable","error"):
            limits.append(f"Engine {run['engine']}: {run['status']}.")
    limits.extend(warnings)
    recommendation = "Review highlighted evidence and verify against original records." if reasons else "Verify against original records before relying on the document; absence of flags is not proof of authenticity."
    return Explanation(summary=summary,reasons=reasons,limitations=list(dict.fromkeys(limits)),recommendation=recommendation)

