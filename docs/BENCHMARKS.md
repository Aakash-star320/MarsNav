# Analyzer benchmarks

Measured on 2026-11-14 with `backend/scripts/benchmark_analyzer.py`: Python 3.14.0, numpy 2.3.5, Windows 11, 12 logical CPUs, one analysis at a time. Re-run the script on the target machine before quoting these numbers elsewhere; the deployment target (a small CPU container) has not been benchmarked.

## Processing stages (offline, synthetic elevation grids)

| Cells | Derivatives + bundle write | Verified reload | Map package (257 px display) | Peak memory (build) |
|---|---|---|---|---|
| 10,000 (100 x 100) | 0.05 s | 0.03 s | 0.28 s | 2 MB |
| 99,856 (316 x 316) | 0.13 s | 0.03 s | 0.53 s | 8 MB |
| 1,000,000 (1000 x 1000) | 0.94 s | 0.11 s | 1.41 s | 79 MB |

One million cells is the routing-grid cap in the specification. "Peak memory" is the Python/NumPy allocation peak from `tracemalloc` for the bundle build only; process memory was not measured.

## End to end against the live sources

| Case | Cells | Wall time | Elevation bytes (calculated) | Targets |
|---|---|---|---|---|
| small area (about 3 km), terrain only | 49 | 4.5 s | 0.8 MB | 0 |
| about 1,900 km2, terrain only | 9,373 | 8.5 s | 8.6 MB | 0 |
| about 600 km2, terrain + CRISM | 1,794 | 60.9 s | 3.8 MB | 1 |

- Wall time includes network transfer and is dominated by it, so it varies with the connection and the servers. The CRISM case is slow because the PDS Geosciences Node answered slowly (timeouts and retries were seen during development); the CRISM bands themselves are about 2.7 MB each.
- The elevation byte column is calculated from the number of whole rows read, not metered. CRISM bytes and process memory for the live runs were not measured.
- The 2,500 km2 area limit and the 64 MiB elevation read limit are configuration, chosen conservatively; they have not been tuned against a deployment target.
