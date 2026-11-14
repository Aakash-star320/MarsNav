# Frontend integration contract

The dashboard developer owns the shell/layout and feature panels. The map developer owns `features/mars-map` as an independently testable module mounted through an explicit props/store contract. Both share Zustand `missionStore`; neither directly manipulates the other's DOM.

State includes selected mission/AOI/base/destination, active analysis/job, layers and visibility/opacity, selected target, active/alternative route, blocked areas, navigation state and UI loading/error states. API data is normalized by `src/api` adapters into `src/types/contracts.ts` types. Fixtures use exactly the same shapes.

| Event | Producer → consumer | Effect |
|---|---|---|
| map coordinate/AOI pick | Map → store/dashboard | populate location controls; user can start analysis |
| target selection | either → store → both | card and marker highlight/focus |
| analysis completion | API/dashboard → store/map | render only ready layers with coverage/limits |
| route result | dashboard/API → store/map | metrics panels and polylines/waypoints update atomically |
| blocked draw | map → dashboard/API | show pending replan; replace only on response |
| navigation tick | HUD → store/map | astronaut marker and instruction update |

Map controls show per-layer source/coverage and opacity; unavailable layers remain visibly unavailable. 3D receives DEM layer/affine metadata and route geometry, never decorative height. The dashboard owns forms, presets, progress, warnings, cards/chat/HUD. All coordinate formatting calls a shared convention utility.
