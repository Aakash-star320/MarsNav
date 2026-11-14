# Git workflow

Branches: `feature/analyzer-ai` (Aakash), `feature/dashboard`, `feature/mars-map`, `feature/routing`, and `feature/data-cache`. Start from updated `main`; do not merge another feature branch directly into your own without review. Use conventional, scoped commits.

PRs name owner, issue/task, files changed, contract impact, fixture impact, tests, and UI screenshots. Aakash is integration lead and reviews backend/shared-contract changes; dashboard/map owners cross-review integration changes. Squash merge after CI/approval. Resolve conflicts with the owning developer, never by silently dropping contract updates.

Contract change procedure: create a small proposal PR updating Pydantic models, OpenAPI snapshot, TS mirror, documentation and fixtures together; get all producer/consumer owner approval; only then change modules. Feature PRs may not introduce frameworks, endpoints, DB tables or duplicated state outside frozen decisions.
