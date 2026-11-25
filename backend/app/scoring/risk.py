"""Provisional heuristic, not a calibrated fraud probability."""
WEIGHTS = {"visual": .30, "file_forensics": .20, "consistency": .50}
MIN_COVERAGE = .60
MIN_CONFIDENCE = .50

def calculate(runs):
    scores = {}
    excluded = {r["engine"] for r in runs if r["status"] == "not_applicable" and r.get("findings") and all(f["status"] == "not_applicable" for f in r["findings"])}
    applicable = sum(v for k,v in WEIGHTS.items() if k not in excluded)
    for run in runs:
        name = run["engine"]
        if name not in WEIGHTS or run["status"] != "completed":
            continue
        usable = [f for f in run.get("findings", []) if f["status"] in ("passed", "suspicious") and f["confidence"] >= MIN_CONFIDENCE]
        if usable:
            scores[name] = max(f["score"] for f in usable)
    observed = sum(WEIGHTS[k] for k in scores)
    coverage = observed / applicable if applicable else 0
    if coverage < MIN_COVERAGE:
        return dict(risk_score=None, risk_level="inconclusive", coverage=round(coverage, 4))
    score = round(100 * sum(WEIGHTS[k]*v for k,v in scores.items()) / observed, 2)
    level = "high" if score >= 70 else "medium" if score >= 35 else "low"
    # Partial analysis cannot establish low overall risk.
    if coverage < .999 and level == "low":
        level = "inconclusive"
    return dict(risk_score=score if level != "inconclusive" else None, risk_level=level, coverage=round(coverage,4))
