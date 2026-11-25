# Proposed v1 contract
POST /analyze multipart field file -> HTTP 202 {job_id,status}.
GET /result/{id} -> {job_id,status,risk_score,risk_level,coverage,findings,pages}.
Job status: queued, running, completed, failed. Risk score nullable until sufficient evidence. Risk level: low, medium, high, inconclusive.
Each finding uses DetectorResult in backend/app/schemas.py. Boxes use zero-based page index and original rendered pixel coordinates, top-left origin. Pages include page index, width, height and preview URL. Missing checks are not clean results.
This is a contract proposal; endpoints are not implemented yet.
