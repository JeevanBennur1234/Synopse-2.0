"""Offline demonstration adapter. Never verifies government registration."""
from typing import Literal
from pydantic import BaseModel
from app.detectors.consistency.gstin import compute_gstin_checksum

class RegistryCheck(BaseModel):
    gstin: str
    status: Literal["mock_match", "not_in_fixture", "invalid_format", "uncertain_ocr"]
    message: str
    mode: Literal["mock"] = "mock"
    authoritative: Literal[False] = False

# Deliberately synthetic PAN-style identifiers; not sourced from real businesses.
PREFIX = "29ZZZZZ0000Z1Z"
FIXTURE_ID = PREFIX + compute_gstin_checksum(PREFIX)

def check_registry(fields, locations):
    checks = []
    for candidate in dict.fromkeys(fields.get("gstin", [])):
        candidate = candidate.strip().upper()
        matches = [x for x in locations.get("gstin", []) if x.get("value","").upper() == candidate]
        if any(x.get("confidence") is not None and x["confidence"] < .65 for x in matches):
            status, message = "uncertain_ocr", "OCR uncertainty prevents a reliable fixture lookup."
        elif len(candidate) != 15 or not candidate.isascii() or not candidate.isalnum() or compute_gstin_checksum(candidate[:14]) != candidate[-1]:
            status, message = "invalid_format", "Candidate is not suitable for mock lookup; consult structural validation."
        elif candidate == FIXTURE_ID:
            status, message = "mock_match", "Matches a synthetic demonstration record only."
        else:
            status, message = "not_in_fixture", "Not in the synthetic fixture; real registration status is unknown."
        checks.append(RegistryCheck(gstin=candidate,status=status,message=message))
    return checks

