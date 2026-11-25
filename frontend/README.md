# Kavach Frontend

React + Vite + Tailwind CSS workbench for Kavach business document tampering analysis.

## Setup

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

Open http://localhost:5173.

## Environment Variables

- `VITE_API_BASE_URL` (default `/api`): Proxied by Vite dev server to `http://localhost:8000` so local development works without backend CORS changes.

## Scripts

- `npm run dev` — Start Vite development server on port 5173
- `npm run build` — Production build to `frontend/dist`
- `npm test` — Run Vitest unit and UI integration tests
