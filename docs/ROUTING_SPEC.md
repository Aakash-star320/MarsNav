# Routing specification

Routing owns terrain derivation and consumes a `RegionalAnalysisResult` with elevation/validity/projection plus optional roughness, hazard and science layers. It produces no scientific evidence and does not download data.

Build a local metric grid from the analyzer grid. Derive slope and roughness with documented window/cell-neighbour algorithms, preserving NoData. Form traversability as hard exclusions: invalid/unknown according to mission policy, slope above max, user blocked cells, and any explicitly forbidden hazard. Never use a soft weight to bypass a hard condition.

For traversable neighbours, deterministic A* uses non-negative edge costs: distance × weighted normalized terrain factors; science can reduce cost only to a positive lower bound. The heuristic is admissible relative to that lower bound. Tie-break deterministically by cell ordering. Record formula/version and layer versions in result provenance.

Prototype defaults: max slope 12°, reserve 20%, and user-visible traversal-speed assumption. They are not NASA EVA limits. Presets are named bundles: Safest (hazard/confidence/slope high), Shortest (distance high), Balanced, Science-focused (science high). Restore defaults restores the documented bundle.

Route metrics include projected distance, duration under labeled speed assumption, maximum slope, ascent-only elevation gain, terrain/hazard summary, score, warnings, coverage confidence, selected targets and route geometry. For return missions, concatenate/check Base → targets → Base against total hard limits and reserve; do not certify only the outward leg. Required targets are mandatory stops; practical multi-stop ordering can be heuristic and must disclose it.

Replanning inserts `BlockedArea` geometry, reuses immutable original route request/analysis version, and explains material differences. No feasible path returns `feasible:false`, empty geometry, and machine/user-readable conflicts. Navigation samples/simplifies waypoints, calculates bearing, relative turn and remaining distance from simulated position/heading.
