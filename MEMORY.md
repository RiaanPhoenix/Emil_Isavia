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
| `fd58abb` | Add live feed functionality for real-time parking occupancy monitoring |
| `f928da2` | INTEGRATED: Premium Parking API Connection |
| `71bb1b1` | CORRECTED: Implement actual problem — Isavia Premium Valet Parking |
| `ccc57d4` | Initial implementation: Aviation Traffic Optimization System |

---

## Current State (2026-03-28)

- Full optimization + simulation pipeline functional
- Real parking API integrated (`parking_api.py`)
- Live feed for real-time occupancy monitoring added
- GurobiPy with heuristic fallback (no license required for dev)
- Flight data: OpenSky (free), AviationStack, AirLabs supported
- Frontend: 3-step workflow (Generate → Optimize → Simulate)

---

## Known Issues / TODOs

- [ ] No `.env.example` confirmed present — verify API key setup
- [ ] Gurobi license not available in dev; heuristic fallback in use
- [ ] Tests in `tests/` — coverage status unknown
- [ ] Docker setup in README but not verified

---

## Notes

- Emil will be working on this project heavily going forward
- First memory file created: 2026-03-28
