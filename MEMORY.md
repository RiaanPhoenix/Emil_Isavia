# Emil_Isavia — Project Memory

## What This Is
Premium Valet Parking Optimization system for Isavia at Keflavík Airport (BIKF).
Workers move customer cars between zones: Móttökustæði (reception/drop-off), Gull storage, P3 storage, Skilastæði (arrival/pick-up).

---

## Architecture

### Zones & Capacities
| Zone | Role | Cap |
|---|---|---|
| Móttökustæði | Customer drop-off spot | 14 |
| Gull | Storage (preferred) | 50 |
| P3 | Storage (overflow) | 150 |
| Skilastæði | Customer pick-up spot | **14** (hard limit) |

### Two Worker Moves Per Car
- **MOVE1**: Móttökustæði → storage (Gull or P3), on the departure day
- **MOVE2**: storage → Skilastæði, on the arrival day (must arrive ≥90 min before flight)

### Backhaul Optimization
After a MOVE1, the worker is already at the storage zone. If another car there needs MOVE2 within 4 hours, the worker drives it to Skilastæði instead of walking back empty. Only happens if:
1. Car is physically already in storage
2. Return deadline within 4h (BACKHAUL_WINDOW_H)
3. Deadline hasn't passed
4. Skilastæði has free capacity

---

## Key Files
| File | Purpose |
|---|---|
| `app.py` | Flask app, all routes |
| `app/optimization/greedy_scheduler.py` | Core scheduler — `schedule_range()`, `schedule_day()`, `fifo_schedule()` |
| `app/api/parking_api.py` | Parking API client (Azure) |
| `app/api/flights.py` | Flight data + mock booking generator |
| `app/templates/index.html` | Main page — date range picker, schedule table, timeline |
| `app/templates/dashboard.html` | Analytics dashboard with same scheduler UI |
| `config/settings.py` | Travel times, capacities, API config |
| `valet_optimizer.py` | Standalone CLI optimizer (separate from web app) |

---

## API Endpoints
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/greedy-schedule` | POST | Single-day schedule (compat) |
| `/api/greedy-schedule-range` | POST | Date range schedule |
| `/api/status` | GET | System status |
| `/api/live-status` | GET | Live parking occupancy |

### Request format for `/api/greedy-schedule-range`
```json
{
  "date_from": "2026-05-05",
  "date_to": "2026-05-11",
  "day_movers": 2,
  "night_workers": 2,
  "supervisor": true,
  "move2_window": 60
}
```

### Task field schema (in response)
| Field | Description |
|---|---|
| `type` | `MOVE1` or `MOVE2` |
| `carId` | Booking/plate ID |
| `storage` | `Gull` or `P3` |
| `worker` | `W1` or `W2` |
| `movingMin` | Duration of the drive (minutes) |
| `move` | Human label e.g. `Móttökustæði → Gull` |
| `moveStart` | When worker starts the move |
| `moveEnd` | When worker finishes the move |
| `dropoffTime` | When customer drops car at reception |
| `depFlight` | Departure flight time |
| `arrFlight` | Arrival flight time |
| `arrReadyBy` | Car must be at Skilastæði by this time |
| `storageDeadline` | Car must be in storage by this time |
| `noReturnReason` | Why no backhaul was assigned (MOVE1 only) |

---

## Scheduler Design (as of 2026-05-05)

Uses **absolute time model** (minutes since 2000-01-01 00:00:00).
This correctly handles cars dropped off days/weeks ago that return today.

Per day, `fifo_schedule()` receives:
- `move1_cars` — cars whose drop-off falls today
- `move2_cars` — cars whose return deadline falls today
- `storage_pool` — cars already in storage from prior days

Storage pool carries across days within a range run, so capacity is tracked correctly.

---

## Known Issues / To Do (2026-05-05)

1. **MOVE1 timing** — currently pinned to 23:49 (storage_ddl − move duration) when no worker is free earlier. Should schedule as close to actual dropoff time as possible, not just before deadline.
2. **Backhaul window** — 4h may need tuning based on real traffic patterns. With real API data, check if backhauled trips actually appear.
3. **Real API credentials** — `.env` file needs `PARKING_API_USERNAME` and `PARKING_API_PASSWORD`. Without them, system falls back to mock bookings seeded by date.
4. **Responsive table** — many columns on the schedule table, needs collapsing on mobile.
5. **CLI vs web** — `valet_optimizer.py` (root level) and `app/optimization/greedy_scheduler.py` are separate. Should eventually unify.
6. **No authentication** — Flask runs in debug mode, no login.
7. **Security** — repo is PUBLIC, old API password in git history. Must rotate + make private + scrub.

---

## Security Note
⚠️ Repo is PUBLIC. Old password `Dunder.Mifflin!26` is in git history.
Actions needed:
1. Rotate Azure API password
2. Make GitHub repo private
3. Optionally: `git filter-repo` to scrub history

---

## Session History
- **2026-05-05**: Full scheduler rewrite, date range UI, backhaul tightening, field schema overhaul, `.slice` crash fixes
- **2026-04-29**: Nav/path fixes, parking dashboard work
- **2026-04-28**: Initial parking dashboard build
