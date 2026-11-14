# Instructions for AI coding agents

1. Read `docs/PROJECT_SPEC.md`, `docs/SYSTEM_ARCHITECTURE.md`, `docs/API_CONTRACTS.md`, `docs/DATA_MODELS.md`, `docs/COORDINATE_CONVENTIONS.md`, and your member task.
2. Modify only your owned folders. Ask the integration lead before crossing boundaries.
3. Reuse `backend/app/schemas` and `frontend/src/types/contracts.ts`; do not create parallel models or a second API app/store.
4. Use canonical planetocentric latitude and east-positive longitude in `[-180, 180)` internally. Never assume Earth CRS defaults.
5. Treat unavailable data as unavailable; never synthesize observations, science evidence, or safe terrain.
6. Build against the documented interfaces first: provide interfaces, mocks, validation, and documentation before real-data implementation.
7. Add or update tests and fixtures with each behavior change. Report files changed, commands run, and contract effects in the PR.
8. Do not silently change a contract. Propose the versioned change in a dedicated PR and update both generated OpenAPI and frontend types together.
