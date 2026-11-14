import { create } from "zustand";
import type { LonLat, RouteResult, ScienceTarget } from "../types/contracts";
type MissionState = { selectedPoint?:LonLat; selectedTargetId?:string; activeRoute?:RouteResult; targets:ScienceTarget[]; setSelectedPoint:(point:LonLat)=>void; setSelectedTarget:(id?:string)=>void; setActiveRoute:(route?:RouteResult)=>void; setTargets:(targets:ScienceTarget[])=>void };
export const useMissionStore = create<MissionState>((set)=>({targets:[], setSelectedPoint:(selectedPoint)=>set({selectedPoint}), setSelectedTarget:(selectedTargetId)=>set({selectedTargetId}), setActiveRoute:(activeRoute)=>set({activeRoute}), setTargets:(targets)=>set({targets})}));
