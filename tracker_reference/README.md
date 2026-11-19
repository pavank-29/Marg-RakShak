# MargRakshak AI — Tracker Reference Architecture & Integration

## Overview
This folder (`tracker_reference/`) serves as the architectural benchmark and reference prototype for high-frequency (1-second), low-latency real-time GPS telemetry and multi-vehicle fleet tracking.

Originally authored as a standalone Express + Socket.io + Leaflet prototype (`app.js`, `script.js`, `style.css`, `index.ejs`), its core algorithms, telemetry data formats, and UI patterns have been cleanly integrated into the main MargRakshak full-stack application.

---

## Architectural Mapping & Integration

| Prototype Component (`tracker_reference`) | Integrated MargRakshak Production Component | Responsibilities & Optimizations Added |
|---|---|---|
| `app.js` (Express + Socket.io Server) | `BackEnd/app/api/v1/endpoints/tracking.py` | Converted to native FastAPI WebSockets + REST API (`/ws/{client_id}`, `/fleet`, `/update`). Added non-blocking concurrent `asyncio.gather` broadcast, per-socket timeout protection (0.8s), threadpool offloading (`run_in_threadpool`) for ML risk scoring, 15-second background inactivity sweeper, and dictionary concurrency safety. |
| `script.js` (Socket.io Client) | `FrontEnd/src/hooks/useTrackingSocket.js` | Converted to React hook with dynamic URL resolution (Vite dev proxy + production URLs), exponential reconnect backoff with jitter (1s to 8s), RTT ping latency monitoring, and imperative packet emitter (`sendLocation`). |
| `script.js` (LERP Loop & Marker Icons) | `FrontEnd/src/components/MapView.jsx` (`SmoothVehicleMarker`) | 60 FPS `requestAnimationFrame` linear interpolation for smooth motion without GPS jumping, shortest-circular-arc bearing interpolation, live beacon pulse, directional heading cone, and multi-vehicle fleet rendering. |
| `style.css` (Tracker HUD & Beacons) | `FrontEnd/src/index.css` & `FrontEnd/src/components/common/TelemetryHUD.jsx` | Full Tailwind CSS + Glassmorphism design tokens for directional beacons, speed gauges, heading cones, and floating telemetry HUD. |
| Standalone Driver UI | `FrontEnd/src/pages/user/UserNavigation.jsx` & `FrontEnd/src/pages/admin/AdminMap.jsx` | Driver navigation telemetry HUD + Admin real-time city-wide fleet dispatch tracking. |

---

## Status
- **Backend Service**: Native FastAPI WebSocket at `/api/v1/tracking/ws/{client_id}` and REST at `/api/v1/tracking/fleet`.
- **Frontend Layer**: Seamlessly rendered in `MapView` across both User and Admin modules with full toggle controls.
- **Verification**: Fully covered by backend integration test suite (`tests/test_tracking.py`) and frontend Vite build.
