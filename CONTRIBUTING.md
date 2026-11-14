# Contributing

Work only from the branch assigned in `docs/GIT_WORKFLOW.md`. Read `AGENTS.md`, the shared contracts, and your member task before changing code.

Do not modify shared schemas, API paths, coordinate conventions, dependency manifests, or the application shell without an approved contract-change PR. Keep PRs small and scoped to owned folders. Include contract impact, fixture changes, tests run, and screenshots for UI changes. Aakash reviews backend integration and all shared-contract changes.

Run `pytest` for backend changes and `npm run lint && npm test` for frontend changes. Do not commit raw NASA products, local databases, model weights, credentials, or generated geospatial artifacts.
