# Frozen technology stack

| Area | Choice | Rule |
|---|---|---|
| Backend | Python 3.11, FastAPI, Pydantic v2 | One application and OpenAPI source |
| Persistence | PostgreSQL 16, SQLAlchemy 2, Alembic | PostGIS deferred; filesystem stores rasters |
| Geospatial | GDAL (system), Rasterio, pyproj, Shapely, NumPy; optional xarray/GeoPandas | Use explicit Mars CRS/metadata |
| Frontend | React 18, TypeScript 5, Vite, Tailwind, Zustand | One shared store |
| 2D / 3D | Leaflet + custom Mars CRS; React Three Fiber/Three.js | 3D terrain must come from DEM |
| AI | Ollama, one small tool-capable local model selected at event; sentence-transformers + sqlite-vec | Tool outputs remain authoritative |
| Tests | pytest, Vitest/Testing Library, Playwright later | Synthetic fixture labels required |
| Local services | Docker Compose for PostgreSQL only | No microservices, brokers, or Kubernetes |

Use `pip install -e '.[dev]'` and `npm install` after versions are frozen in lockfiles during the event. Lockfiles are deliberately not generated in the initial scaffolding because package resolution is an implementation/environment decision; do not change dependency families without a contract PR. Run `uvicorn app.main:app --reload`, `pytest`, `npm run dev`, `npm run lint`, and `npm test`.

ISIS is optional and only entered when a product family has a documented, tested ISIS workflow; its container/install is not a blanket dependency. No frontend geospatial calculation substitutes backend analysis.
