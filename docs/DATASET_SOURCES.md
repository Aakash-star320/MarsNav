# Dataset sources and verification status

The initial connectors are adapters, not assertions that every product has a GeoTIFF or usable footprint. Before an event implementation selects a source, record its endpoint request/response sample, license/terms, coordinate semantics, product label, download URL and processing support in a connector test fixture.

| Source/family | Intended role | Status and handling |
|---|---|---|
| PDS Search API / Peppi | PDS4 catalogue discovery | PDS documents programmatic Search API/Peppi; endpoint parameters still need connector-level verification before use. |
| PDS Geosciences Mars ODE | footprint/product discovery across several Mars missions | ODE publicly advertises a REST interface and mission/instrument search; validate parameters/product links against the selected instrument. |
| USGS Astropedia MOLA DEM | global elevation fallback | Product page documents a 463 m global MOLA DEM and download link; use local clipped derivative, not browser-scale full raster. |
| USGS regional CTX/HiRISE/DEM products | high-resolution local imagery/elevation where coverage exists | Product-specific labels decide projection, control and suitability. |
| CRISM / THEMIS PDS products | spectral/thermal evidence | Supported only after a chosen processed product family and validation workflow are demonstrated. |

Official starting references: [PDS Search](https://pds.nasa.gov/services/search/index.jsp), [Mars ODE](https://ode.rsl.wustl.edu/mars2/), [USGS MOLA DEM](https://astrogeology.usgs.gov/search/map/mars_mgs_mola_dem_463m), and [USGS Mars data inventory](https://fdp.astrogeology.usgs.gov/fdp/mars/). These establish availability, not a blanket processing guarantee.

Selection ranks actual AOI overlap, valid coverage, processing level, spatial resolution, objective relevance, source quality, known limitations and workflow support. A global MOLA DEM cannot establish individual-rock obstacles. Missing a category yields partial analysis, never fake coverage.
