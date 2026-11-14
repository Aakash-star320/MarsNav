# MarsNav

MarsNav is a collaboration-ready blueprint for a NASA Space Apps 2026 Martian Marswalk planner. This repository contains the shared contracts, fixtures, module boundaries, and application scaffolding.

Read [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md), [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md), and your document in [`docs/MEMBER_TASKS`](docs/MEMBER_TASKS) before coding.

## Quick start

1. Copy `.env.example` to `.env` and set local values.
2. `docker compose up -d db` starts PostgreSQL for development.
3. Backend: `cd backend; python -m venv .venv; .venv\Scripts\activate; pip install -e '.[dev]'; uvicorn app.main:app --reload`.
4. Frontend: `cd frontend; npm install; npm run dev`.

The FastAPI OpenAPI document is available at `/docs`; it is the executable complement to `docs/API_CONTRACTS.md`.

## Repository rules

One FastAPI app, one frontend, and one source of truth for contracts. Keep downloaded products and generated rasters out of Git. Use the member feature branch and open a PR; see `CONTRIBUTING.md`.
