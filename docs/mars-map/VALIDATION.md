# Validation report

Validated in the build environment on 2026-11-14.

| Check | Result |
|---|---|
| TypeScript + Vite production build | Passed |
| ESLint | Passed |
| Unit/component tests | 62 passed: 35 geometry, 19 store/fixture, 6 rendered-control tests, 2 current-contract fixture tests |
| Chromium production-browser tests | 4 passed |
| Desktop 2D and 3D screenshots | Captured and visually inspected |
| 390px mobile viewport | No horizontal document overflow |

Browser coverage: overlay visibility/opacity; target selection; navigation playback; blocked-area drawing/reason/confirmation; explicit fixture response; actual WebGL terrain and orbit; height exaggeration; target selection across views; missing DEM; unsupported projection; no feasible route; broken image asset; no data; responsive layout.

The updated map files were applied to a separate copy of MarsNav-main (2).zip, with current contracts preserved. Stage 1 build/lint passed. Stage 2 build/lint and the tests above passed. Files outside the update manifests were verified unchanged. Test count alone is not a coverage guarantee.

Not verified: actual NASA data, live backend or dashboard integration, mission-version race handling in a real API, real route feasibility/scientific claims, hardware/browser combinations beyond this Chromium run. Windows commands are provided but this build environment is Linux. The PowerShell application script was reviewed, but was not executed on Windows. 3D requires WebGL; a clear fallback is shown if unavailable.

The browser tests run with software WebGL support enabled. No uncaught page exceptions were observed in the tested 2D/3D interaction flows. Screenshots are demo-only and contain no user account data.
