# Kavach — Synapse 2.0
Defence-only business document tampering analysis. Python 3.11 / FastAPI, React / Vite, SQLite.
See [TEAM_TASKS.md](docs/TEAM_TASKS.md) and [API_CONTRACT.md](docs/API_CONTRACT.md).

> **Security & Deployment Notice**: Kavach is a demonstration screening system with **no authentication or access control** built in. **Do not expose this service publicly** on the internet or untrusted networks; bind to `127.0.0.1` / an isolated local environment and analyse only synthetic or consented documents.

### JPEG error-level analysis limitation

Error-level analysis can flag localized differences in JPEG recompression history. A
globally re-saved splice can remain inconclusive, as on the annotated grand-total
region in invoice_tampered_visual_ela.jpg. Develop flagged a separate region on
that fixture, with zero overlap with the annotated splice. The invoice arithmetic
check still flags the altered total.
