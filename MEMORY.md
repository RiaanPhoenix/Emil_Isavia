# MEMORY.md — Emil_Isavia Project

> Long-term project memory. Updated as work progresses.

---

## Overview

**Emil_Isavia** — Premium Valet Parking Optimization & Simulation system for Isavia at Keflavík International Airport (BIKF).

- **Repo:** `git@github.com:RiaanPhoenix/Emil_Isavia.git`
- **Local:** `/home/claw/.openclaw/workspace-worker-two/Emil_Isavia/`
- **Stack:** Python 3.8+, Flask, GurobiPy (MILP optimizer), SimPy (discrete-event simulation)
- **Frontend:** Bootstrap HTML templates + vanilla JS

---

## The Problem

Isavia's Premium valet parking service at Keflavík:
- Customers drop cars at **Reception** (14 spots) before departure
- Staff move cars to storage: **Gull** (50 spots, close) or **P3** (150 spots, far)
- Cars must be at **Delivery** (20 spots) ≥15 min before customer return
- **Hard constraint:** Cars MUST be ready on time
- **Objective:** Minimize total staff time

### Physical Layout
```
Reception (14) ──3min──► Gull (50) ──4min──► Delivery (20)
     │                                          ▲
     └────8min──► P3 (150) ──────9min──────────┘
```

---

## Architecture

```
app/
├── api/
│   ├── flights.py          # OpenSky / AviationStack / AirLabs integration
│   └── parking_api.py      # Real Isavia valet booking API
├── optimization/
│   └── valet_optimizer.py  # GurobiPy MILP model (+ heuristic fallback)
├── simulation/
│   └── valet_sim.py        # SimPy Monte Carlo simulation
├── static/
│   ├── css/style.css
│   └── js/main.js
└── templates/
    ├── base.html
    ├── index.html
    ├── optimize.html
    └── simulate.html

config/settings.py          # All config + env vars
app.py                      # Main Flask entrypoint
```

---

## Key Config

| Parameter | Value |
|---|---|
| Airport ICAO | BIKF |
| Reception capacity | 14 |
| Gull capacity | 50 |
| P3 capacity | 150 |
| Delivery capacity | 20 |
| Delivery lead time | 15 min |
| Time slot granularity | 15 min |
| Planning horizon | 24 h |
| Max staff | 10 |
| Sim runs (Monte Carlo) | 10 |

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/bookings` | Generate valet bookings |
| POST | `/api/optimize` | Run optimization model |
| POST | `/api/simulate` | Run simulation |
| GET | `/api/status` | System health check |

---

## Git History

| Hash | Message |
|---|---|
| `5bb878b` | Fix: mock bookings now vary by date (was using fixed random seed) |
| `8d690c5` | UX: hide customer count field when using real parking API |
| `4ff0ae2` | Fix: numpy int64 JSON serialisation error and simulation zone-sync bug |
| `ade8d1f` | Redesign: clean professional UI — navy/slate palette, Inter typography, refined layout |
| `fd58abb` | Add live feed functionality for real-time parking occupancy monitoring |
| `f928da2` | INTEGRATED: Premium Parking API Connection |
| `71bb1b1` | CORRECTED: Implement actual problem — Isavia Premium Valet Parking |
| `ccc57d4` | Initial implementation: Aviation Traffic Optimization System |

---

## Current State (2026-03-28)

- Full optimization + simulation pipeline functional
- Real parking API integrated (`parking_api.py`) — credentials not yet set
- Live feed for real-time occupancy monitoring added
- GurobiPy with heuristic fallback (no license required for dev)
- Flight data: OpenSky (free), AviationStack, AirLabs supported
- Frontend: 3-step workflow (Generate → Optimize → Simulate)
- UI fully redesigned — navy/slate palette, Inter font, professional look

---

## Known Issues / TODOs

- [ ] Real Parking API not connecting — needs `PARKING_API_USERNAME` + `PARKING_API_PASSWORD` in `.env`
- [ ] Gurobi license not available in dev; heuristic fallback in use
- [ ] Tests in `tests/` — coverage status unknown
- [ ] Docker setup in README but not verified

---

## Bugs Fixed (2026-03-28)

- **numpy int64 JSON crash** — simulation returned numpy scalar types; fixed by casting all to `float()`/`int()` before response
- **Simulation zone-sync** — planned moves fired before car arrived at source zone; fixed with up-to-60-min tolerance wait
- **Mock data fixed seed** — all dates returned identical bookings; fixed by seeding RNG from date (`YYYYMMDD`)
- **Customer count field** — shown even when using real API; now hidden unless Mock mode selected

---

## Notes

- Emil working on this project heavily
- Memory file created: 2026-03-28
