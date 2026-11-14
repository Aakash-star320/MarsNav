import { beforeEach, describe, it, expect } from "vitest";
import { useMissionStore as store } from "../../../store/missionStore";
import {
  loadDemo,
  mission,
  demoLayers,
  applyFixtureResponse,
} from "../fixtures";
beforeEach(() => loadDemo());
describe("mission transitions", () => {
  it("invalidates routes on base change", () => {
    store.getState().setBase(mission.destination);
    expect(store.getState().activeRoute).toBeUndefined();
    expect(store.getState().alternatives).toHaveLength(0);
  });
  it("clears derived region data on AOI change", () => {
    store.getState().setAoi(mission.bounds);
    expect(store.getState().layers).toHaveLength(0);
    expect(store.getState().dem).toBeUndefined();
    expect(store.getState().targets).toHaveLength(0);
  });
  it("cancels unfinished selection without clearing AOI", () => {
    store.getState().setMode("aoi");
    store.getState().pick(mission.base);
    store.getState().cancel();
    expect(store.getState().aoi).toEqual(mission.bounds);
    expect(store.getState().first).toBeUndefined();
  });
  it("draws and confirms AOI only after two points", () => {
    const s = store.getState();
    s.setMode("aoi");
    s.pick(mission.base);
    expect(store.getState().draft).toBeUndefined();
    s.pick(mission.destination);
    expect(store.getState().draft).toBeDefined();
    s.confirm();
    expect(store.getState().mode).toBe("inspect");
  });
  it("requires blocked reason", () => {
    const s = store.getState();
    s.setMode("blocked");
    s.pick(mission.base);
    s.pick(mission.destination);
    s.confirm();
    expect(store.getState().blockedAreas).toHaveLength(0);
    expect(store.getState().error).toContain("reason");
  });
  it("emits typed blocked area and marks replan pending", () => {
    const s = store.getState();
    s.setMode("blocked");
    s.pick(mission.base);
    s.pick(mission.destination);
    store.setState({ reason: "Fixture obstacle" });
    s.confirm();
    expect(store.getState().blockedAreas[0].reason).toBe("Fixture obstacle");
    expect(store.getState().replan).toBe("pending");
    expect(store.getState().activeRoute).toEqual(mission.route);
  });
  it("preserves target selection across view changes", () => {
    store.getState().setSelectedTarget(mission.targets[0].id);
    store.getState().setView("3d");
    expect(store.getState().selectedTargetId).toBe(mission.targets[0].id);
  });
  it("does not fabricate replan for changed mission", () => {
    store.getState().setBase(mission.destination);
    applyFixtureResponse();
    expect(store.getState().activeRoute?.feasible).toBe(false);
  });
  it("uses recorded response only for matching fixture", () => {
    applyFixtureResponse();
    expect(store.getState().activeRoute?.feasible).toBe(true);
  });
  it("refuses prerecorded routes if all intersect blocks", () => {
    store.setState({
      blockedAreas: [{ bounds: mission.bounds, reason: "Entire region" }],
    });
    applyFixtureResponse();
    expect(store.getState().activeRoute?.feasible).toBe(false);
  });
  it("does not mutate invalid coordinates into the store", () => {
    expect(() =>
      store.getState().setBase({ latitude_deg: 99, longitude_deg_east: 0 }),
    ).toThrow();
    expect(store.getState().base).toEqual(mission.base);
  });
});
describe("independent layers", () => {
  it("keeps opacity and visibility independent", () => {
    const s = store.getState();
    s.setLayerOpacity("fixture-imagery", 0.2);
    s.setLayerVisibility("fixture-hazard", true);
    expect(store.getState().layerSettings["fixture-imagery"]).toEqual({
      visible: true,
      opacity: 0.2,
    });
    expect(store.getState().layerSettings["fixture-hazard"].visible).toBe(true);
  });
  it.each([-0.1, 1.1, NaN, Infinity])("rejects invalid opacity", (v) =>
    expect(() =>
      store.getState().setLayerOpacity("fixture-imagery", v),
    ).toThrow(),
  );
  it("rejects unknown layer", () =>
    expect(() =>
      store.getState().setLayerVisibility("unknown", true),
    ).toThrow());
  it("removes stale display settings", () => {
    store.getState().setLayers([demoLayers[0]]);
    expect(Object.keys(store.getState().layerSettings)).toHaveLength(1);
  });
  it("rejects duplicate layer IDs", () =>
    expect(() =>
      store.getState().setLayers([demoLayers[0], demoLayers[0]]),
    ).toThrow());
});
