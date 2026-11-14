import { describe, expect, it } from "vitest";
import { demoLayers, mission } from "../fixtures";

describe("current contract fixture compatibility", () => {
  it("includes required route collections in serialized fixtures", () => {
    for (const route of [mission.route, ...mission.alternatives]) {
      for (const field of ["segments", "elevation_profile", "alternatives", "conflict_details"] as const) {
        expect(Array.isArray(route[field])).toBe(true);
      }
    }
  });
  it("declares availability and limitations for every display layer", () => {
    for (const { layer, coverage } of demoLayers) {
      expect(layer.availability).toBe(coverage);
      expect(layer.limitations.length).toBeGreaterThan(0);
    }
  });
});
