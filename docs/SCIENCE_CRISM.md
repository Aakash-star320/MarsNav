# Science objective: hydrated hydroxylated-mineral candidates (CRISM)

Supported objective: an analysis whose objective text mentions hydrated minerals, minerals, clay, phyllosilicate or smectite adds a science stage after the terrain stage. Other objectives run terrain only and say so.

## Data (verified 2026-11-14)

- **Product family:** PDS dataset `MRO-M-CRISM-5-RDR-MPTARGETED-V1.0`, bundle `mrocr_4001` at https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/ . ODE (`ihid=MRO`, `iid=CRISM`, `pt=MTRDR`, `loc=f` footprint intersection) lists the observations and their files.
- **File read:** the spectral-summary-parameter cube `..._SU<n>J_MTR3.IMG` with its ENVI header `.HDR`. The real header and label were read and are kept in `backend/tests/fixtures/crism`: 60 bands, 32-bit little-endian float, band-sequential, ignore value 65535, equirectangular on a sphere of radius 3394839.813 m, standard parallel 15 N, 18 m pixels (36 m for half-resolution HRL observations). The server answers byte-range requests, so one band of the analysis window is one range request (about 2.7 MB for a full 808-row scene); the 164 MB cube is never downloaded.
- **Real-data check:** seven targeted observations cover the Jezero area in ODE; a run over 77.30-77.65 E, 18.20-18.50 N used two of them (74% valid coverage) and produced one low-confidence candidate near 18.36 N, 77.41 E.

## What the documentation supports

The PDS labels of the browse product **PHY** ("hydroxylated minerals including phyllosilicate") name `D2300`, `D2200` and `BD1900R2` as its red, green and blue parameters and describe the colours: Mg/Fe-OH bearing minerals "may appear red, or magenta when hydrated"; Al/Si-OH bearing minerals "may appear green, or cyan when hydrated". Every browse label states: "Analysis of CRISM spectra must be used to match absorption band positions and relative strength for positive mineral identification" and cites Viviano-Beck et al. [2014] for the parameter definitions. All 18 browse definitions are recorded in `browse_definitions.json`. The labels give **no numeric detection threshold**.

The labels' 8-bit scaling (`SCALING_FACTOR x 254`) is the parameter value at which each browse image saturates. It is identical across the three observations compared, so it is a fixed, documented stretch: D2300 0.0339, D2200 0.0174, BD1900R2 0.0497.

## The rule (a heuristic, reported as one)

1. `n_p = clip(value_p / stretch_p, 0, 1)` for D2300, D2200, BD1900R2.
2. Evidence `e = min(max(n_D2300, n_D2200), n_BD1900R2)`: an OH absorption **and** a hydration absorption must both be strong (the "magenta or cyan when hydrated" condition).
3. Candidate pixel: all three parameters valid and `e >= 0.5` (half of the browse stretch).
4. Connected pixels (8-neighbourhood) form a group; groups under 25 pixels are dropped.
5. Rank `0.7 x mean(e) + 0.3 x min(1, pixels / 400)`; confidence is `medium` only for at least 100 pixels with mean evidence of 0.75 or more, otherwise `low`. Confidence reflects strength and extent, never mineral identity.

The thresholds (0.5, 25 pixels, 400, 100, 0.75) are configurable choices made here. They are **not** published criteria.

## What a result means

- A target is a **candidate spectral signature**: a place where two documented summary parameters are both strong. It is not an identified mineral and not a probability.
- Each target carries two evidence entries: the measured parameter means (with their share of the browse stretch, the pixel count and area, the product ID and a PDS link) and the heuristic rule with its citation and limitations.
- Missing data stay missing. Areas without CRISM coverage, invalid pixels and areas with no candidate are never reported as absence of minerals; the analysis warnings say so.
- CRISM data may be old, partial or unavailable. If discovery or reading fails, the terrain analysis still completes and a warning explains why there are no targets.

## Not supported

Other mineral families (carbonates, sulfates, mafic minerals: their browse definitions are recorded but no detector uses them), the full-resolution I/F spectral cubes, spectrum-level matching, atmospheric or ice interference screening, multi-observation mosaicking and uncertainty estimates.
