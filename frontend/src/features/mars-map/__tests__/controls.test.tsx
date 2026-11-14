import React from "react";
import { beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import {
  render,
  screen,
  fireEvent,
  cleanup,
  act,
} from "@testing-library/react";
vi.mock("../Map2D", () => ({ Map2D: () => <div>2D test surface</div> }));
import { MarsMap } from "../MarsMap";
import { loadDemo, mission } from "../fixtures";
import { useMissionStore as store } from "../../../store/missionStore";
beforeEach(() => loadDemo());
afterEach(cleanup);
describe("map control integration", () => {
  it("toggles only the requested overlay", () => {
    render(<MarsMap />);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "hazard visibility" }),
    );
    expect(store.getState().layerSettings["fixture-hazard"].visible).toBe(true);
    expect(store.getState().layerSettings["fixture-imagery"].visible).toBe(
      true,
    );
  });
  it("updates opacity through the slider", () => {
    render(<MarsMap />);
    fireEvent.change(screen.getByRole("slider", { name: "imagery opacity" }), {
      target: { value: "0.3" },
    });
    expect(store.getState().layerSettings["fixture-imagery"].opacity).toBe(0.3);
  });
  it("shows selected science target", () => {
    render(<MarsMap />);
    fireEvent.click(screen.getByRole("button", { name: /Western outcrop/ }));
    expect(store.getState().selectedTargetId).toBe(mission.targets[0].id);
  });
  it("shows no-route conflicts from shared state", () => {
    render(<MarsMap />);
    act(() =>
      store
        .getState()
        .setActiveRoute({
          ...mission.route,
          feasible: false,
          geometry: [],
          constraint_conflicts: ["Fixture conflict"],
        }),
    );
    expect(screen.getByText("Fixture conflict")).toBeTruthy();
  });
  it("shows no-data state", () => {
    store.setState({ layers: [] });
    render(<MarsMap />);
    expect(
      screen.getByText("No processed layers. Coverage is unknown."),
    ).toBeTruthy();
  });
  it("emits a blocked-area callback once", () => {
    const cb = vi.fn();
    render(<MarsMap onBlockedArea={cb} />);
    fireEvent.click(screen.getByRole("button", { name: "Block" }));
    act(() => {
      store.getState().pick(mission.base);
      store.getState().pick(mission.destination);
    });
    fireEvent.change(
      screen.getByRole("textbox", { name: "Blocked area reason" }),
      { target: { value: "Test obstacle" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm block" }));
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb.mock.calls[0][0].reason).toBe("Test obstacle");
  });
});
